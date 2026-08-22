"""Set the pieces as a part: stacked down A4, at a size somebody can read."""

from __future__ import annotations

import io
from pathlib import Path

from ..model import Extraction
from ..paper import MM, PageSetup
from ..reflow import scale_for
from . import register


class PdfExporter:
    suffix = ".pdf"

    def write(
        self,
        extraction: Extraction,
        path: Path,
        page_size: str = "a4",
        landscape: bool = False,
        margin_mm: float = 14.0,
        gap_mm: float = 5.0,
        staff_mm: float = 1.75,
        title: str = "",
        subtitle: str = "",
        show_sources: bool = False,
        heading: bool = True,
        **_,
    ) -> Path:
        import pymupdf

        setup = PageSetup(size=page_size, landscape=landscape, margin_mm=margin_mm,
                          gap_mm=gap_mm, staff_mm=staff_mm)
        page_w, page_h = setup.width_pt(), setup.height_pt()
        margin = margin_mm * MM
        gap = gap_mm * MM
        usable_w = page_w - 2 * margin

        doc = pymupdf.open()
        page = None
        cursor = 0.0

        def new_page(first: bool = False) -> None:
            nonlocal page, cursor
            page = doc.new_page(width=page_w, height=page_h)
            cursor = margin
            if first and heading and (title or extraction.part_name):
                cursor = _draw_heading(
                    page, margin, cursor, usable_w,
                    title or extraction.source,
                    subtitle or extraction.part_name,
                )
            elif heading:
                page.insert_text(
                    (page_w - margin, margin - 4),
                    f"{extraction.part_name}   {doc.page_count}",
                    fontsize=7, fontname="helv", color=(0.45, 0.45, 0.45),
                    render_mode=0,
                )

        new_page(first=True)

        for segment in extraction.segments:
            scale = scale_for(segment.band.space, segment.dpi, staff_mm)
            src_h, src_w = segment.image.shape[:2]
            width_pt = src_w / segment.dpi * 72.0 * scale
            height_pt = src_h / segment.dpi * 72.0 * scale
            if width_pt > usable_w:  # a piece that still overflows is shrunk to fit
                height_pt *= usable_w / width_pt
                width_pt = usable_w
            if cursor + height_pt > page_h - margin:
                new_page()
            rect = pymupdf.Rect(margin, cursor, margin + width_pt, cursor + height_pt)
            page.insert_image(rect, stream=_png_bytes(segment.image))
            if show_sources:
                page.insert_text(
                    (margin + width_pt + 2, cursor + 6),
                    f"{segment.band.page_index + 1}"
                    + (f".{segment.chunk + 1}" if segment.of > 1 else ""),
                    fontsize=5, fontname="helv", color=(0.6, 0.6, 0.6),
                )
            cursor += height_pt + gap

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(path, deflate=True)
        doc.close()
        return path


def _draw_heading(page, margin: float, cursor: float, usable_w: float,
                  title: str, part: str) -> float:
    page.insert_text((margin, cursor + 14), title, fontsize=15, fontname="hebo")
    page.insert_text((margin, cursor + 30), part, fontsize=10, fontname="helv",
                     color=(0.25, 0.25, 0.25))
    return cursor + 40


def _png_bytes(arr) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


register("pdf", PdfExporter())
