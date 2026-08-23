"""Retyping: from a scan to freshly engraved sheet music.

This is the second half of the job, and it is a different kind of thing from the
first.  Cutting a part out of a score is geometry — it either lands on the right
staff or it does not, and you can see which.  Retyping means *reading* the
music, and a machine that reads music makes mistakes that look plausible.

So the process here is built to be checkable rather than to look impressive:

1.  Extract the part (the verified half) and lay it out as a clean draft page —
    no title, no page numbers, nothing but staves.  An engine handed the
    original score would have to find the right staff among nineteen; handed a
    single strip it has too little to work with.  A page of the part is the
    thing it was trained on.
2.  Recognise each page.  The engine is somebody else's program, named at the
    edge (`recognize/engines.py`) rather than wired in.
3.  Join the pages into one part and **count**.  Two numbers are checked
    without any human looking: how many bars the barline detector saw in the
    scan, and how many measures came back; and whether each measure's notes add
    up to its own time signature.  A measure that does not add up is wrong, full
    stop, and that is worth knowing before anybody plays from it.
4.  Engrave with LilyPond.

What comes out is a fresh PDF plus a report naming the bars to look at.  It is
a draft to proofread, not a finished part, and `RetypeResult.trustworthy` says
so in one boolean rather than in prose.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from . import barnum, crop, marks as marks_mod, score_xml
from .reconcile import (
    bars_from_numbers, drop_what_the_page_denies, numbers_are_worth_using,
    reconcile, staves_by_page,
)
from .engrave import LilyPondEngraver
from .model import Extraction
from .paper import PageSetup
from .pipeline import extract_part, write as write_extraction
from .recognize import Recognizer, get_recognizer
from .reflow import system_barlines
from .score_xml import MeasureCheck

Progress = Callable[[str], None]


@dataclass
class PageSpan:
    """Which measures of the finished part came off which page of the score.

    This is what makes proofreading possible.  A flagged measure is no use on
    its own — "measure 147 does not add up" sends nobody anywhere.  With the
    span it becomes "measure 147 is on page 14 of the score", and the bar can be
    found and fixed in a few seconds.
    """

    source_page: int  # 1-based, as printed in the PDF reader
    first_measure: int
    last_measure: int

    @property
    def measures(self) -> int:
        return self.last_measure - self.first_measure + 1


@dataclass
class RetypeResult:
    part_name: str
    engine: str
    musicxml: Path | None
    fresh_pdf: Path | None
    draft_pdf: Path | None
    bars_in_scan: int
    measures_read: int
    checks: list[MeasureCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spans: list[PageSpan] = field(default_factory=list)
    bars_by_page: dict[int, int] = field(default_factory=dict)
    proof_pdf: Path | None = None
    guessed: list[int] = field(default_factory=list)

    @property
    def bad_measures(self) -> list[MeasureCheck]:
        """Measures to look at: ones that do not add up, and ones that were
        filled in to make them add up.  A guess that has been tidied away is
        still a guess."""
        suspect = [c for c in self.checks if not c.ok]
        seen = {c.number for c in suspect}
        by_number = {c.number: c for c in self.checks}
        for number in self.guessed:
            if number not in seen and number in by_number:
                suspect.append(by_number[number])
        return sorted(suspect, key=lambda c: c.number)

    @property
    def trustworthy(self) -> bool:
        """Every measure adds up and the bar count matches the scan."""
        return (
            bool(self.checks)
            and not self.bad_measures
            and not self.guessed
            and self.measures_read == self.bars_in_scan
        )

    def page_of(self, measure: int) -> int | None:
        for span in self.spans:
            if span.first_measure <= measure <= span.last_measure:
                return span.source_page
        return None

    def report(self) -> dict:
        """Everything a person needs to proofread, as data."""
        return {
            "part": self.part_name,
            "engine": self.engine,
            "measures_read": self.measures_read,
            "bars_in_scan": self.bars_in_scan,
            "trustworthy": self.trustworthy,
            "musicxml": str(self.musicxml) if self.musicxml else None,
            "pdf": str(self.fresh_pdf) if self.fresh_pdf else None,
            "pages": [
                {
                    "score_page": span.source_page,
                    "measures": [span.first_measure, span.last_measure],
                    "bars_in_scan": self.bars_by_page.get(span.source_page),
                    "read": span.measures,
                    "suspect": [
                        c.number for c in self.bad_measures
                        if span.first_measure <= c.number <= span.last_measure
                    ],
                }
                for span in self.spans
            ],
            "suspect_measures": [
                {"measure": c.number, "score_page": self.page_of(c.number),
                 "adds_up_to": str(c.beats), "should_be": str(c.expected)}
                for c in self.bad_measures
            ],
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        state = "clean" if self.trustworthy else "needs proofreading"
        return (
            f"{self.part_name}: {self.measures_read} measures read by {self.engine}, "
            f"{self.bars_in_scan} bars counted in the scan, "
            f"{len(self.bad_measures)} measure(s) that do not add up — {state}"
        )


def count_bars_by_page(extraction: Extraction) -> dict[int, int]:
    """How many written bars the scan holds, from the barlines already found.

    This is the cross-check that costs nothing: the layout stage had to find the
    barlines anyway in order to cut the systems at them, so the number of bars
    in the source is known before any recognition happens.  A multi-bar rest
    counts as one written bar here, which is also how MusicXML counts it.

    It is an estimate, not a census.  Counted across the system it agreed with
    Audiveris exactly on three of the first four pages and was four over on the
    other; counted on one staff alone it was useless — a cornet part playing
    semiquavers offered 46 "barlines" in a 13-bar system.
    """
    pages = {page.page.index: page for page in extraction.detected}
    seen: set[tuple[int, int]] = set()
    total: dict[int, int] = {}
    for segment in extraction.segments:
        band = segment.band
        key = (band.page_index, band.system_index)
        if key in seen:
            continue
        seen.add(key)
        page = pages.get(band.page_index)
        if page is None:
            continue
        system = page.systems[band.system_index]
        found = system_barlines(page, system)
        total[band.page_index + 1] = total.get(band.page_index + 1, 0) + max(0, len(found) - 1)
    return total


def retype(
    source: str | Path,
    part: str = "bottom",
    out: str | Path = "fresh.pdf",
    pages: str | Sequence[int] | None = None,
    dpi: float | str = "auto",
    engine: Recognizer | str | None = None,
    omr_dpi: float = 400.0,
    omr_staff_mm: float = 2.2,
    staff_size: float = 20.0,
    paper: str = "a4",
    landscape: bool = False,
    part_name: str = "",
    title: str = "",
    read_from: str = "score",
    workdir: str | Path | None = None,
    reuse: bool = False,
    jobs: int = 1,
    graft: bool = True,
    rehearsal_marks: bool = True,
    proof: str | Path | None = None,
    progress: Progress | None = None,
) -> RetypeResult:
    """Extract a part, read it, and set it again as a fresh PDF."""
    recognizer = engine if isinstance(engine, Recognizer) else get_recognizer(engine)
    if recognizer is None:
        raise RuntimeError(
            "no optical music recognition engine is available.  Install one and "
            "point Sheeets at it: SHEEETS_OEMER, SHEEETS_AUDIVERIS, or a command "
            "template in SHEEETS_OMR_COMMAND (see sheeets.recognize)."
        )

    engraver = LilyPondEngraver()
    if not engraver.available():
        raise RuntimeError(
            "LilyPond is not installed; it is what sets the recognised music "
            "again (needs `lilypond` and `musicxml2ly` on PATH)."
        )

    if read_from not in {"score", "part"}:
        raise ValueError('read_from must be "score" or "part"')

    out = Path(out)
    holder = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="sheeets-retype-"))
    holder.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda _line: None)

    # 1. The part itself, laid out plainly for a machine to read.
    say("extracting the part")
    extraction = extract_part(
        source, part=part, pages=pages, dpi=dpi,
        setup=PageSetup(staff_mm=omr_staff_mm), labels="none",
        part_name=part_name, progress=None,
    )
    if not extraction.segments:
        raise RuntimeError("nothing was extracted; check --part against `sheeets inspect`")
    # The draft is only wanted when the engine is going to read *it*; in score
    # mode nothing ever opens it, and writing one costs a minute of laying out
    # ninety-four images that nobody sees.
    draft = None
    if read_from == "part":
        draft = holder / "draft.pdf"
        write_extraction(extraction, draft, setup=PageSetup(staff_mm=omr_staff_mm),
                         heading=False)

    warnings: list[str] = []
    # What the page itself says about its bars, where it is a part and says
    # anything: the printed bar numbers, the multi-measure rest counts, and how
    # many bars each system holds.  Read before recognition because the count
    # is worth reporting whether or not an engine is any good.
    staff_of_page = staves_by_page(extraction)
    facts = barnum.survey(extraction.detected, staff_of_page)
    if not numbers_are_worth_using(facts):
        facts, wanted = [], {}
    else:
        for line in drop_what_the_page_denies(facts):
            say(line)
            warnings.append(line)
        wanted = barnum.bars_wanted(facts)
    bars_by_page = count_bars_by_page(extraction)
    counted = bars_from_numbers(facts, wanted) if facts else {}
    if counted:
        # The printed numbers beat the barline count whenever they are a
        # numbering at all, and the temptation is to check them against the
        # barlines first.  That was tried and it is backwards: on a part
        # written tightly enough that a stem crosses the staff, the barline
        # count is the wrong one — 518 against 68 on a drum-kit part whose
        # nineteen numbered systems say 75.  What vouches for the numbers is
        # that they are a run: most systems carry one, they ascend, and none
        # of them makes nonsense of its neighbours.
        bars_by_page = counted
        say(f"{sum(counted.values())} bars, from the bar numbers printed on the "
            f"part ({len([f for f in facts if f.number is not None])} of "
            f"{len(facts)} systems carry one)")
    else:
        say(f"{sum(bars_by_page.values())} bars counted in the scan, from the "
            f"barlines — an estimate; see `system_barlines`")
    bars = sum(bars_by_page.values())

    # 2. Recognition, one page at a time.
    #
    # Which pages depends on how the engine is being used, and the difference
    # matters more than it looks.  Handing it the *score* lets it do what it was
    # built for — read a system of nineteen staves, work out the parts, keep
    # each one's clef — and the part wanted is then chosen out of its answer by
    # staff position.  Handing it the extracted *part* seems simpler and reads
    # worse: the draft's lines are pieces of systems, so most of them begin in
    # the middle of a phrase with no clef, and the engine has nothing to anchor
    # on.  Measured on this score, reading the score pages found nearly twice
    # as many measures as reading the part draft.
    marks_of_page: dict[int, list[tuple[int, str]]] = {}
    if read_from == "score":
        if rehearsal_marks:
            marks_of_page = _find_marks(extraction, say)
        images = _rasterise_source(source, sorted(staff_of_page), holder / "pages",
                                   dpi=omr_dpi)
    else:
        staff_of_page = {}
        images = _rasterise(draft, holder / "pages", dpi=omr_dpi)

    say(f"reading {len(images)} page(s) with {recognizer.name}, from the {read_from}"
        + (f", {jobs} at a time" if jobs > 1 else ""))

    def read_one(item: tuple[int, Path]) -> tuple[int, Path]:
        page_index, image = item
        cached = holder / "xml" / f"{image.stem}.musicxml"
        if reuse and cached.exists():
            return page_index, cached
        return page_index, recognizer.recognize_page(image, holder / "xml")

    produced: list[tuple[int, Path]] = []
    if jobs > 1:
        # The engines are subprocesses, so threads are the right shape here and
        # a page is entirely independent of its neighbours.  Audiveris takes
        # about four minutes on a nineteen-stave page; three at a time turns a
        # two-hour run into forty minutes.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(read_one, item): item for item in images}
            done = 0
            for future in as_completed(futures):
                page_index, image = futures[future]
                done += 1
                try:
                    produced.append(future.result())
                    say(f"  page {done}/{len(images)} done (p{page_index + 1})")
                except Exception as exc:
                    warnings.append(f"page {page_index + 1}: {_brief(exc)}")
                    say(f"  page {done}/{len(images)} FAILED (p{page_index + 1})")
    else:
        for n, item in enumerate(images, start=1):
            try:
                produced.append(read_one(item))
                say(f"  page {n}/{len(images)} done")
            except Exception as exc:
                warnings.append(f"page {item[0] + 1}: {_brief(exc)}")
                say(f"  page {n}/{len(images)} FAILED")

    trees = []
    read_pages: list[tuple[int, int]] = []
    grafted = 0
    lettered = 0
    for page_index, produced_path in sorted(produced):  # back into playing order
        try:
            page_tree = score_xml.read(produced_path)
            tree = page_tree
            if read_from == "score":
                tree = score_xml.select_staff(page_tree, staff_of_page[page_index])
                if graft:
                    grafted += score_xml.graft_directions(page_tree, tree)
                # Repair before placing: a mark is put at a measure, and the
                # repair is what decides which measure a printed bar is.
                for line in reconcile(tree, facts, wanted, page_index):
                    say(line)
                    warnings.append(line)
                found = marks_of_page.get(page_index)
                if found:
                    lettered += _place_marks(tree, found)
            trees.append(tree)
            read_pages.append((page_index, score_xml.count_measures(tree)))
        except Exception as exc:
            warnings.append(f"page {page_index + 1}: {_brief(exc)}")
    if not trees:
        raise RuntimeError(f"{recognizer.name} could not read any page")

    if grafted:
        say(f"{grafted} tempo marking(s) taken from the top staff")
    if lettered:
        say(f"{lettered} rehearsal mark(s) read off the score and added")

    # 3. Join and count.
    tree = score_xml.merge_trees(trees, part_name=part_name or extraction.part_name)
    seams = score_xml.smooth_seams(tree)
    for line in seams:
        say(line)
    repairs = score_xml.sanitize(tree)
    for line in score_xml.tame_text(tree):
        say(line)
        warnings.append(line)
    for line in score_xml.strip_stray_lyrics(tree):
        say(line)
        warnings.append(line)
    doubled = score_xml.dedupe_directions(tree)
    if doubled:
        say(f"{doubled} marking(s) printed twice; one copy kept")
    shown = score_xml.show_bar_rests(tree)
    if shown:
        say(f"{shown} whole-bar rest(s) made visible, so multi-bar rests are drawn "
            f"as one bar with a number rather than as empty bars")
    guesses = score_xml.fill_incomplete(tree)
    # After the bar filler, not before it.  The filler pads a short bar with a
    # rest of exactly the length that is missing, and that rest has no written
    # value either — so naming the values first left fifteen unnamed rests in
    # the file that goes to the engraver, and musicxml2ly died on them exactly
    # as it did before the naming existed.
    for line in score_xml.name_durations(tree):
        say(line)
        warnings.append(line)
    repairs.extend(str(g) for g in guesses)
    guessed = sorted({g.measure for g in guesses if g.measure})
    if guessed:
        say(f"{len(guessed)} bar(s) had to be filled or padded: they are flagged")
    if repairs:
        warnings.extend(repairs)
        say(f"{len(repairs)} structural repair(s) before engraving")
    score_xml.set_titles(tree, title=title, part_name=part_name or extraction.part_name)
    musicxml = score_xml.write(tree, out.with_suffix(".musicxml"))
    checks = score_xml.check(tree)
    measures = score_xml.count_measures(tree)
    say(f"{measures} measures read, {sum(1 for c in checks if not c.ok)} do not add up")

    # 4. Set it again.
    say("engraving")
    engraved = engraver.engrave(musicxml, out, staff_size=staff_size,
                                paper=paper, landscape=landscape)

    spans: list[PageSpan] = []
    at = 0
    for page_index, count in read_pages:
        if count <= 0:
            continue
        spans.append(PageSpan(source_page=page_index + 1, first_measure=at + 1,
                              last_measure=at + count))
        at += count

    result = RetypeResult(
        part_name=part_name or extraction.part_name,
        engine=recognizer.name,
        musicxml=musicxml,
        fresh_pdf=engraved.pdf,
        draft_pdf=draft,
        bars_in_scan=bars,
        measures_read=measures,
        checks=checks,
        warnings=warnings + extraction.warnings,
        spans=spans,
        bars_by_page=bars_by_page,
        guessed=guessed,
    )
    if proof:
        from .proof import write_proof

        result.proof_pdf = write_proof(extraction, result, proof)
        say(f"proof sheet: {result.proof_pdf}")
    say(result.summary())
    return result


def _find_marks(extraction: Extraction, say) -> dict[int, list[tuple[int, int, str]]]:
    """Rehearsal letters, read off the page by shape: page -> (system, bar, text).

    They are found on the page rather than in the recognised MusicXML because
    the OMR engine does not see them: a boxed letter above a nineteen-stave
    system is not text it can pick out, but it is the most distinctive shape on
    the page.  See `sheeets.marks`.

    Every system on the page is looked at, not only the first.  On a score
    there is one system to a page and it made no difference; on a *part* there
    are a dozen, and looking at the first alone found three letters out of
    fifteen and put them in the wrong bars.

    One setting for the box detector, not a search over several.  A looser
    setting was tried, on the reasoning that a part's printed frames are often
    broken: it doubles the boxes found, and on this score the extra ones read
    as a *longer* run — A to U where the piece has A to O — so a search that
    keeps the longest run would confidently place six marks that do not exist.
    A run is good evidence that what was read is real; it is not evidence that
    nothing else was invented.

    The place is kept as (system, bar within that system) rather than as a
    measure number, because a multi-measure rest is one bar on the page and
    several measures in the recognition, so the two only line up once the
    recognised systems are in hand.
    """
    places, letters = _read_boxes(extraction)
    tidied, corrections, kept = marks_mod.tidy_sequence(letters)
    for line in corrections:
        say(f"rehearsal mark: {line}")
    if tidied:
        say("rehearsal marks: " + " ".join(tidied))
    else:
        say("rehearsal marks: none could be read with confidence; "
            "the fresh part carries none — put them in by hand")
    return _by_page(places, tidied, kept)


def _by_page(places, letters, kept) -> dict[int, list[tuple[int, int, str]]]:
    # Strays can be dropped from anywhere in the run, so line the places up
    # with the items that survived rather than with what was read.
    here = [places[i] for i in kept] if len(kept) == len(letters) else places
    out: dict[int, list[tuple[int, int, str]]] = {}
    for (page_index, system_index, bar), text in zip(here, letters):
        out.setdefault(page_index, []).append((system_index, bar, text))
    return out


def _read_boxes(extraction: Extraction):
    places: list[tuple[int, int, int]] = []  # page, system, bar in system
    letters: list[str] = []
    for page in extraction.detected:
        floor = 0.0
        for system_index, system in enumerate(page.systems):
            if not system.staves:
                continue
            top = system.staves[0]
            # How far above the staff to look.  On a score, twelve spaces of
            # empty margin; on a part there is another system that close, and
            # searching into it turned its noteheads and multi-measure rest
            # numbers into rehearsal boxes.  Never look past the staff above.
            reach = min(12.0, max(1.5, (top.top - floor) / top.space - 0.3))
            floor = system.staves[-1].bottom
            found = marks_mod.find_marks(page.image, top.top, top.space,
                                         reach_spaces=reach)
            if not found:
                continue
            bars = system_barlines(page, system)
            for mark in found:
                places.append((page.page.index, system_index,
                               marks_mod.measure_of(mark, bars)))
                letters.append(mark.text)
    return places, letters


def _place_marks(tree, found: list[tuple[int, int, str]]) -> int:
    """Turn (system, bar) places into measure numbers and write the marks in."""
    spans = score_xml.systems_of(tree)
    placed: list[tuple[int, str]] = []
    for system_index, bar, text in found:
        if system_index >= len(spans):
            continue
        printed = score_xml.written_bars(tree, spans[system_index])
        if not printed:
            continue
        index = printed[min(bar, len(printed) - 1)][0]
        placed.append((index, text))
    return score_xml.add_rehearsal_marks(tree, placed)


def _rasterise(pdf: Path, folder: Path, dpi: float) -> list[tuple[int, Path]]:
    import pymupdf

    folder.mkdir(parents=True, exist_ok=True)
    out: list[tuple[int, Path]] = []
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            path = folder / f"draft{index + 1:03d}.png"
            page.get_pixmap(dpi=int(dpi)).save(path)
            out.append((index, path))
    return out


def _rasterise_source(
    source, indices: list[int], folder: Path, dpi: float
) -> list[tuple[int, Path]]:
    """The original pages, as the OMR engine should see them."""
    from PIL import Image

    from .sources import open_source

    src = source if not isinstance(source, (str, Path)) else open_source(source)
    folder.mkdir(parents=True, exist_ok=True)
    out: list[tuple[int, Path]] = []
    for index in indices:
        path = folder / f"score{index + 1:03d}.png"
        if not path.exists():
            Image.fromarray(src.load(index, dpi).array).save(path)
        out.append((index, path))
    return out


def _brief(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[-1][:200] if text else exc.__class__.__name__
