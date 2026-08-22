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

    # What the page itself says about its bars, where it is a part and says
    # anything: the printed bar numbers, the multi-measure rest counts, and how
    # many bars each system holds.  Read before recognition because the count
    # is worth reporting whether or not an engine is any good.
    facts = barnum.survey(extraction.detected) if _is_a_part(extraction) else []
    wanted = barnum.bars_wanted(facts) if facts else {}
    bars_by_page = count_bars_by_page(extraction)
    if facts:
        counted = _bars_from_numbers(facts, wanted)
        if counted:
            bars_by_page = counted
    bars = sum(bars_by_page.values())
    printed = [f.number for f in facts if f.number is not None]
    if printed:
        say(f"{bars} bars, from the bar numbers printed on the part "
            f"({len(printed)} of {len(facts)} systems carry one)")
    else:
        say(f"{bars} bars counted in the scan")

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
    warnings: list[str] = []
    marks_of_page: dict[int, list[tuple[int, str]]] = {}
    if read_from == "score":
        staff_of_page = {
            segment.band.page_index: segment.band.staff_index
            for segment in extraction.segments
        }
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
                for line in _reconcile(tree, facts, wanted, page_index):
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


def _is_a_part(extraction: Extraction) -> bool:
    """Is this source a part rather than a score?

    One staff per system is what makes a part a part, and it is also what makes
    the page's own bar numbers and multi-measure rest counts belong to the
    music being extracted.  On a score they belong to whichever instrument is
    printed at the top of the system, which is not the one being cut out, so
    reading them there would be worse than not reading them at all.
    """
    systems = [s for page in extraction.detected for s in page.systems]
    return bool(systems) and all(len(s.staves) == 1 for s in systems)


def _fit_counts(read: list[int | None], target: int) -> tuple[list[int] | None, str]:
    """Make the multi-measure rest counts add up to what the page demands.

    The total is not in doubt: the difference between two printed bar numbers
    is exactly how many bars the system holds, so once the written bars are
    counted the rests' total is forced.  Every count read off the page is then
    checked against it, which turns a pile of small OCR answers into one
    arithmetic question with a right answer.

    One unreadable count is solved for.  One *wrong* count can also be solved
    for, but only when a single position can be changed to fix the sum and the
    new value looks like a misreading of what was read there — 4 for 44, 3 for
    8 — rather than an unrelated number.  Anything less certain is refused and
    reported, because a part with a rest of the wrong length is worse than a
    part that says it does not know.
    """
    if not read:
        return ([], "") if target == 0 else (None, "there are no multi-bar rests")
    blanks = [i for i, count in enumerate(read) if count is None]
    known = sum(count for count in read if count is not None)
    if len(blanks) > 1:
        return None, f"{len(blanks)} of its multi-bar rests could not be read"
    if len(blanks) == 1:
        value = target - known
        if value < 2:
            return None, "the unreadable multi-bar rest would have to be under two bars"
        out = [value if count is None else count for count in read]
        return out, f"one multi-bar rest could not be read; the bar numbers make it {value}"
    counts = [int(count) for count in read]
    if sum(counts) == target:
        return counts, ""
    fixes = []
    for i, count in enumerate(counts):
        value = target - (sum(counts) - count)
        if 2 <= value <= 200 and _plausible_misread(str(count), str(value)):
            fixes.append((i, value))
    if len(fixes) == 1:
        i, value = fixes[0]
        out = list(counts)
        was = out[i]
        out[i] = value
        return out, f"a multi-bar rest read as {was}; the bar numbers make it {value}"
    return None, (f"its multi-bar rests {counts} add up to {sum(counts)} "
                  f"where the bar numbers want {target}")


def _plausible_misread(read: str, wanted: str) -> bool:
    """Could `wanted` have been read as `read` by an OCR of small digits?"""
    if read == wanted:
        return True
    if wanted in read or read in wanted:       # 4 read as 44, 27 read as 2
        return True
    if len(read) == len(wanted):               # one digit confused for another
        return sum(a != b for a, b in zip(read, wanted)) == 1
    return False


def _reconcile(tree, facts, wanted, page_index: int) -> list[str]:
    """Make the recognised bars agree with the numbers printed on the page.

    An engine reads a multi-measure rest by reading the number over it, and
    that is the number it is worst at: measured on a publisher's timpani part,
    every two-digit count came back with its tens digit missing — 16 as 6, 24
    as 4, 34 as 4 — so a 401-bar part was recognised as 255 bars.  Nothing
    inside the MusicXML can notice that.  The printed bar numbers can, because
    the difference between two of them is exactly how many bars lie between.

    So: where the page says a system holds N bars and the recognition produced
    a different number, and the page's own multi-measure rests can account for
    the difference, the rests are set to what the page says.  Where they cannot,
    nothing is changed and the disagreement is reported — a part that says it
    is unsure is worth more than one that quietly invents bars.
    """
    if not facts:
        return []
    notes: list[str] = []
    mine = [f for f in facts if f.page_index == page_index]
    spans = score_xml.systems_of(tree)
    if len(mine) != len(spans):
        return [f"page {page_index + 1}: the scan shows {len(mine)} system(s) and "
                f"the recognition {len(spans)}; the printed bar numbers were not used"]
    for fact, span in reversed(list(zip(mine, spans))):
        want = wanted.get((fact.page_index, fact.system_index))
        if want is None:
            continue
        printed = score_xml.written_bars(tree, span)
        where = f"page {page_index + 1} system {fact.system_index + 1}"
        if span[1] - span[0] == want:
            continue
        if len(printed) != fact.written:
            notes.append(f"{where}: the page has {fact.written} written bar(s) and the "
                         f"recognition {len(printed)}; the printed bar numbers say "
                         f"{want} bar(s) but nothing could be lined up")
            _pad(tree, span, want, where, notes)
            continue
        counts, note = _fit_counts(fact.rests, want - len(printed) + len(fact.rests))
        if counts is None:
            notes.append(f"{where}: the page says {want} bar(s) and "
                         f"{span[1] - span[0]} were read, but {note}")
            _pad(tree, span, want, where, notes)
            continue
        if note:
            notes.append(f"{where}: {note}")
        by_bar = dict(zip(fact.rest_bars, counts))
        for bar in reversed(range(len(printed))):
            index, was = printed[bar]
            now = by_bar.get(bar)
            if now == was:
                continue
            if now is None:
                notes.append(f"{where}: bar {bar + 1} was read as a rest of {was} bar(s) "
                             f"and the page shows no such rest — cut to one bar, check it")
                score_xml.set_multi_rest(tree, index, 1)
            elif was is None:
                notes.append(f"{where}: bar {bar + 1} is a {now}-bar rest on the page "
                             f"and was not read as one — put back")
                score_xml.make_multi_rest(tree, index, now)
            else:
                notes.append(f"{where}: a multi-bar rest read as {was}, "
                             f"the page prints {now}")
                score_xml.set_multi_rest(tree, index, now)
    return notes


def _pad(tree, span, want: int, where: str, notes: list[str]) -> None:
    """Keep the bar count right even when the bars themselves are lost."""
    short = want - (span[1] - span[0])
    if short > 0:
        score_xml.pad_system(tree, span, short)
        notes.append(f"{where}: {short} bar(s) the page has and the recognition does "
                     f"not; put in as rests so the numbering stays right — proofread them")


def _bars_from_numbers(facts, wanted) -> dict[int, int]:
    """Bars per page, taken from the numbers printed on the part.

    Counting barlines is an estimate — it made 414 of a part of 401 bars.  The
    printed numbers are not an estimate: the difference between two of them is
    the answer, and it holds across a system whose own number was not read,
    because the bars are still between the two that were.  They are counted
    against the page the earlier number is on, which is where all but the last
    of them are.

    The last system has no successor to be subtracted from, so its own written
    bars and rests are used.  That is the only guess here and it is confined to
    one system.
    """
    known = [f for f in facts if f.number is not None]
    if len(known) < 2:
        return {}
    out: dict[int, int] = {}
    for this, following in zip(known, known[1:]):
        out[this.page_index + 1] = out.get(this.page_index + 1, 0) + (
            following.number - this.number
        )
    last = facts[-1]
    tail = last.written - len(last.rests) + sum(c or 0 for c in last.rests)
    if last.number is not None and last is not known[-1]:
        tail = 0
    out[last.page_index + 1] = out.get(last.page_index + 1, 0) + max(0, tail)
    return out
