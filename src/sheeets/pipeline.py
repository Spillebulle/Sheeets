"""The one function.

    extract_part("score.pdf", part="bottom", out="perc.pdf")

Everything above this module is a stage that can be replaced; this is the wiring
that runs them in order, and the only place that knows the order.  A caller who
wants something else — their own detector, their own exporter — passes it in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from . import crop, export, reflow, select as select_mod
from .detect import StaffDetector, get_detector
from .model import DetectedPage, Extraction, Segment
from .paper import PageSetup
from .sources import PageSource, open_source, parse_pages

Progress = Callable[[str], None]


def analyse(
    source: str | Path | PageSource,
    pages: str | Sequence[int] | None = None,
    dpi: float | str = "auto",
    detector: StaffDetector | None = None,
    progress: Progress | None = None,
) -> tuple[PageSource, list[DetectedPage], float]:
    """Read and detect, without deciding anything about parts."""
    src = source if isinstance(source, PageSource) else open_source(source)
    if dpi == "auto":
        native = getattr(src, "native_dpi", lambda: 300.0)()
        # Below about 8 px between staff lines the detector starts losing
        # staves, and a scan is usually 300; never go under that.
        dpi = max(300.0, float(native))
    dpi = float(dpi)
    det = detector or get_detector("projection")

    indices = (
        parse_pages(pages, src.page_count())
        if pages is None or isinstance(pages, str)
        else [int(i) for i in pages]
    )

    detected: list[DetectedPage] = []
    for i in indices:
        page = src.load(i, dpi)
        result = det.detect(page)
        if progress:
            progress(
                f"{page.label}: {len(result.systems)} system(s), "
                f"{sum(len(s) for s in result.systems)} staves, "
                f"skew {result.skew_deg:+.2f} deg"
            )
        detected.append(result)
    return src, detected, dpi


def extract_part(
    source: str | Path | PageSource,
    part: str | select_mod.PartSelector = "bottom",
    out: str | Path | None = None,
    pages: str | Sequence[int] | None = None,
    dpi: float | str = "auto",
    setup: PageSetup | None = None,
    detector: StaffDetector | None = None,
    part_name: str = "",
    title: str = "",
    pad_spaces: float = 3.5,
    include_label: bool = True,
    labels: str = "first",
    exporter: str | None = None,
    progress: Progress | None = None,
    **export_options,
) -> Extraction:
    """Cut one part out of a score and write it out.

    `part` is "bottom", "top", "all", an index ("-1", "17"), a range ("17..18")
    or "name:Perc".  `out` decides the format from its suffix: .pdf, .json, or a
    folder for images.  Returns the `Extraction` either way, so a caller can
    export it again differently without re-reading the score.
    """
    setup = setup or PageSetup()
    selector = part if not isinstance(part, str) else select_mod.parse(part)
    src, detected, dpi = analyse(source, pages=pages, dpi=dpi, detector=detector,
                                 progress=progress)

    segments: list[Segment] = []
    warnings: list[str] = []
    pages_used: list[int] = []

    for page in detected:
        if not page.systems:
            warnings.append(f"page {page.page.index + 1}: no staves found, skipped")
            continue
        for system in page.systems:
            chosen = selector.select(system, page)
            if not chosen:
                warnings.append(
                    f"page {page.page.index + 1} system {system.index}: "
                    f"no staff matched {selector.name!r}"
                )
                continue
            band = crop.band_for(
                page, system, chosen,
                pad_spaces=pad_spaces, include_label=include_label,
            )
            if band is None:
                continue
            image = crop.cut(page, band)
            top_row, bottom_row = crop.staff_rows(page, system, band)
            limit = setup.source_width_limit_px(band.space, page.page.dpi)
            keep_label = labels == "all" or (labels == "first" and not segments)
            segments.extend(
                reflow.segments_for_band(
                    image, band, top_row, bottom_row,
                    max_source_width=limit, dpi=page.page.dpi,
                    keep_label_on_first=keep_label,
                )
            )
            pages_used.append(page.page.index)

    name = part_name or _default_name(selector)
    extraction = Extraction(
        part_name=name,
        segments=segments,
        source=getattr(src, "name", str(source)),
        pages_used=sorted(set(pages_used)),
        detected=detected,
        warnings=warnings,
    )

    if out is not None:
        write(extraction, out, setup=setup, exporter=exporter, title=title, **export_options)
    return extraction


def write(
    extraction: Extraction,
    out: str | Path,
    setup: PageSetup | None = None,
    exporter: str | None = None,
    **options,
) -> Path:
    setup = setup or PageSetup()
    path = Path(out)
    name = exporter or export.for_path(path)
    if name == "pdf":
        options.setdefault("page_size", setup.size)
        options.setdefault("landscape", setup.landscape)
        options.setdefault("margin_mm", setup.margin_mm)
        options.setdefault("gap_mm", setup.gap_mm)
        options.setdefault("staff_mm", setup.staff_mm)
    return export.get_exporter(name).write(extraction, path, **options)


def _default_name(selector) -> str:
    return getattr(selector, "name", "part")
