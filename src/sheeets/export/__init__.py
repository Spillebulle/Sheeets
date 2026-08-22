"""Where a part ends up.

An exporter takes the finished `Extraction` and writes it somewhere.  Three ship
— a PDF part, one image per piece, and a JSON manifest of the geometry — and a
fourth (MusicXML) is a named place for a recogniser to be plugged in rather than
a promise that one exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from ..model import Extraction


@runtime_checkable
class Exporter(Protocol):
    suffix: str

    def write(self, extraction: Extraction, path: Path, **options) -> Path: ...


_REGISTRY: dict[str, Exporter] = {}


def register(name: str, exporter: Exporter) -> None:
    _REGISTRY[name] = exporter


def get_exporter(name: str) -> Exporter:
    if name not in _REGISTRY:
        raise KeyError(f"no exporter named {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available() -> list[str]:
    return sorted(_REGISTRY)


def for_path(path: Path) -> str:
    """Guess the exporter from the output name."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".json":
        return "manifest"
    if suffix in {".xml", ".musicxml", ".mxl"}:
        return "musicxml"
    if suffix in {"", None} or path.is_dir():
        return "images"
    return "images"


from . import images, manifest, musicxml, pdf  # noqa: E402,F401  (they register)

__all__ = ["Exporter", "register", "get_exporter", "available", "for_path"]
