"""One PNG per piece, for pasting into anything that is not a PDF."""

from __future__ import annotations

from pathlib import Path

from ..model import Extraction
from . import register


class ImageExporter:
    suffix = ""

    def write(self, extraction: Extraction, path: Path, prefix: str = "", **_) -> Path:
        from PIL import Image

        folder = Path(path)
        folder.mkdir(parents=True, exist_ok=True)
        stem = prefix or _slug(extraction.part_name)
        for n, segment in enumerate(extraction.segments, start=1):
            name = f"{stem}-{n:03d}-p{segment.band.page_index + 1}"
            if segment.of > 1:
                name += f"-{segment.chunk + 1}of{segment.of}"
            Image.fromarray(segment.image).save(folder / f"{name}.png", optimize=True)
        return folder


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text.strip()]
    return "".join(keep).strip("-") or "part"


register("images", ImageExporter())
