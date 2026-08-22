"""The proof sheet: the scan of the bars a machine is unsure about.

A report that says "measure 147 does not add up" is only half an answer.  To fix
it somebody has to find bar 147 in the source, and in a 29-page score that is
the slow part of the job.

So the proof sheet prints the scan of every page whose measures were flagged —
the same crops the extracted part is made of, at reading size — with the measure
range that came off that page and which of them to look at.  Open it next to the
MusicXML in a notation editor and the loop is: read the flag, look at the bar,
correct it, move on.

Pages the checker is happy with are left out.  A proof sheet of everything is a
copy of the part, and nobody reads it.
"""

from __future__ import annotations

import io
from pathlib import Path

from .model import Extraction
from .paper import MM, PageSetup
from .reflow import scale_for


def write_proof(
    extraction: Extraction,
    result,  # RetypeResult; typed loosely to keep the import one-way
    path: str | Path,
    setup: PageSetup | None = None,
    staff_mm: float = 2.0,
    only_suspect: bool = True,
) -> Path:
    import pymupdf
    from PIL import Image

    setup = setup or PageSetup()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wanted: dict[int, list[int]] = {}
    for span in result.spans:
        suspect = [c.number for c in result.bad_measures
                   if span.first_measure <= c.number <= span.last_measure]
        counted = result.bars_by_page.get(span.source_page)
        short = counted is not None and counted != span.measures
        if suspect or short or not only_suspect:
            wanted[span.source_page] = suspect

    by_page: dict[int, list] = {}
    for segment in extraction.segments:
        by_page.setdefault(segment.band.page_index + 1, []).append(segment)

    page_w, page_h = setup.width_pt(), setup.height_pt()
    margin = setup.margin_mm * MM
    usable = page_w - 2 * margin

    document = pymupdf.open()
    page = None
    cursor = 0.0

    def new_page(heading: str) -> None:
        nonlocal page, cursor
        page = document.new_page(width=page_w, height=page_h)
        page.insert_text((margin, margin + 10), heading, fontsize=11, fontname="hebo")
        cursor = margin + 22

    if not wanted:
        new_page(f"{result.part_name}: nothing flagged")
        page.insert_text((margin, cursor + 10),
                         "Every measure adds up and the bar counts match the scan.",
                         fontsize=9, fontname="helv")
        document.save(path)
        document.close()
        return path

    for source_page in sorted(wanted):
        span = next(s for s in result.spans if s.source_page == source_page)
        counted = result.bars_by_page.get(source_page)
        suspect = wanted[source_page]
        heading = (
            f"score page {source_page} — measures {span.first_measure}"
            f"–{span.last_measure} ({counted} bars in the scan, {span.measures} read)"
        )
        new_page(heading)
        if suspect:
            page.insert_text(
                (margin, cursor),
                "look at: " + ", ".join(str(n) for n in suspect),
                fontsize=9, fontname="helv", color=(0.7, 0.1, 0.1),
            )
            cursor += 14

        for segment in by_page.get(source_page, []):
            scale = scale_for(segment.band.space, segment.dpi, staff_mm)
            height, width = segment.image.shape[:2]
            width_pt = width / segment.dpi * 72.0 * scale
            height_pt = height / segment.dpi * 72.0 * scale
            if width_pt > usable:
                height_pt *= usable / width_pt
                width_pt = usable
            if cursor + height_pt > page_h - margin:
                new_page(heading + " (continued)")
            rect = pymupdf.Rect(margin, cursor, margin + width_pt, cursor + height_pt)
            buffer = io.BytesIO()
            Image.fromarray(segment.image).save(buffer, format="PNG", optimize=True)
            page.insert_image(rect, stream=buffer.getvalue())
            cursor += height_pt + 6 * MM

    document.save(path, deflate=True)
    document.close()
    return path
