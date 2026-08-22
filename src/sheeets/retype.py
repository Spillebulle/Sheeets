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

from . import crop, score_xml
from .engrave import LilyPondEngraver
from .model import Extraction
from .paper import PageSetup
from .pipeline import extract_part, write as write_extraction
from .recognize import Recognizer, get_recognizer
from .reflow import barlines
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
    draft_pdf: Path
    bars_in_scan: int
    measures_read: int
    checks: list[MeasureCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spans: list[PageSpan] = field(default_factory=list)
    bars_by_page: dict[int, int] = field(default_factory=dict)

    @property
    def bad_measures(self) -> list[MeasureCheck]:
        return [c for c in self.checks if not c.ok]

    @property
    def trustworthy(self) -> bool:
        """Every measure adds up and the bar count matches the scan."""
        return (
            bool(self.checks)
            and not self.bad_measures
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
        image = crop.cut(page, band)
        top, bottom = crop.staff_rows(page, system, band)
        found = barlines(image, top, bottom)
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
    keep: bool = False,
    reuse: bool = False,
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
    draft = holder / "draft.pdf"
    write_extraction(extraction, draft, setup=PageSetup(staff_mm=omr_staff_mm), heading=False)

    bars_by_page = count_bars_by_page(extraction)
    bars = sum(bars_by_page.values())
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
    if read_from == "score":
        staff_of_page = {
            segment.band.page_index: segment.band.staff_index
            for segment in extraction.segments
        }
        images = _rasterise_source(source, sorted(staff_of_page), holder / "pages",
                                   dpi=omr_dpi)
    else:
        staff_of_page = {}
        images = _rasterise(draft, holder / "pages", dpi=omr_dpi)

    say(f"reading {len(images)} page(s) with {recognizer.name}, from the {read_from}")
    trees = []
    read_pages: list[tuple[int, int]] = []
    for n, (page_index, image) in enumerate(images, start=1):
        cached = holder / "xml" / f"{image.stem}.musicxml"
        try:
            if reuse and cached.exists():
                produced_path = cached
                say(f"  page {n}/{len(images)} reused")
            else:
                produced_path = recognizer.recognize_page(image, holder / "xml")
                say(f"  page {n}/{len(images)} read")
            tree = score_xml.read(produced_path)
            if read_from == "score":
                tree = score_xml.select_staff(tree, staff_of_page[page_index])
            trees.append(tree)
            read_pages.append((page_index, score_xml.count_measures(tree)))
        except Exception as exc:  # an engine failing one page must not lose the rest
            warnings.append(f"page {page_index + 1}: {_brief(exc)}")
            say(f"  page {n}/{len(images)} FAILED")
    if not trees:
        raise RuntimeError(f"{recognizer.name} could not read any page")

    # 3. Join and count.
    tree = score_xml.merge_trees(trees, part_name=part_name or extraction.part_name)
    repairs = score_xml.sanitize(tree)
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
        draft_pdf=draft if keep else draft,
        bars_in_scan=bars,
        measures_read=measures,
        checks=checks,
        warnings=warnings + extraction.warnings,
        spans=spans,
        bars_by_page=bars_by_page,
    )
    say(result.summary())
    return result


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
