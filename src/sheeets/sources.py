"""Where pages come from.

A source hands out greyscale page images at a requested dpi and knows nothing
about staves.  Adding a source (a folder of scans, a set of images out of a
camera app) means implementing `PageSource` and registering it in `open_source`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

import numpy as np

from .model import PageImage

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@runtime_checkable
class PageSource(Protocol):
    """Anything that can produce page images."""

    @property
    def name(self) -> str: ...

    def page_count(self) -> int: ...

    def load(self, index: int, dpi: float) -> PageImage: ...


class PdfSource:
    """Pages rasterised out of a PDF with PyMuPDF.

    Rendering at the scan's own resolution matters more than it looks: a full
    score packs twenty staves onto one sheet, so the distance between two staff
    lines is about 11 px at 300 dpi and about 5 px at 150 dpi.  At 5 px the
    detector cannot separate a staff line from a beam and the page comes back
    with a third of its staves missing.  `native_dpi()` reads the resolution the
    scan actually holds so `--dpi auto` does not have to be guessed at.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        import pymupdf  # imported here so the module stays importable without it

        self.path = Path(path)
        self._doc = pymupdf.open(self.path)

    @property
    def name(self) -> str:
        return self.path.name

    def page_count(self) -> int:
        return int(self._doc.page_count)

    def native_dpi(self, sample: int = 8) -> float:
        """The dpi of the biggest image on the first few pages, or 300."""
        best = 0.0
        for i in range(min(sample, self.page_count())):
            page = self._doc[i]
            rect = page.rect
            for img in page.get_images(full=True):
                w_px, h_px = img[2], img[3]
                if rect.width <= 0 or rect.height <= 0:
                    continue
                # The image may be laid down rotated; take the better fit.
                by_width = 72.0 * max(w_px, h_px) / max(rect.width, rect.height)
                best = max(best, by_width)
        return round(best) if best else 300.0

    def load(self, index: int, dpi: float) -> PageImage:
        import pymupdf

        page = self._doc[index]
        pix = page.get_pixmap(dpi=int(round(dpi)), colorspace=pymupdf.csGRAY)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        return PageImage(index=index, array=arr.copy(), dpi=float(dpi), label=f"p{index + 1}")

    def close(self) -> None:
        self._doc.close()


class ImageFolderSource:
    """A folder of page images, sorted by name."""

    def __init__(self, path: str | os.PathLike[str], dpi: float = 300.0) -> None:
        self.path = Path(path)
        self.files = sorted(
            p for p in self.path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
        )
        self._dpi = dpi

    @property
    def name(self) -> str:
        return self.path.name

    def page_count(self) -> int:
        return len(self.files)

    def native_dpi(self, sample: int = 8) -> float:
        return self._dpi

    def load(self, index: int, dpi: float) -> PageImage:
        from PIL import Image

        # An image file carries no page size, so dpi is whatever the caller
        # says it is; rescaling here would only throw away pixels.
        with Image.open(self.files[index]) as im:
            arr = np.asarray(im.convert("L"))
        return PageImage(
            index=index, array=arr, dpi=float(dpi), label=self.files[index].stem
        )


def open_source(path: str | os.PathLike[str], dpi: float = 300.0) -> PageSource:
    p = Path(path)
    if p.is_dir():
        return ImageFolderSource(p, dpi=dpi)
    if p.suffix.lower() == ".pdf":
        return PdfSource(p)
    if p.suffix.lower() in IMAGE_SUFFIXES:
        return ImageFolderSource(p.parent, dpi=dpi)
    raise ValueError(f"don't know how to read {p} (expected a PDF, an image or a folder)")


def parse_pages(spec: str | None, count: int) -> list[int]:
    """"3-", "3-8", "1,3,5-7" -> 0-based page indices."""
    if not spec:
        return list(range(count))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            start = int(a) if a.strip() else 1
            stop = int(b) if b.strip() else count
        else:
            start = stop = int(part)
        out.extend(range(start - 1, min(stop, count)))
    return [i for i in dict.fromkeys(out) if 0 <= i < count]


def iter_pages(source: PageSource, indices: Iterable[int], dpi: float) -> Iterable[PageImage]:
    for i in indices:
        yield source.load(i, dpi)
