"""Turning pixels back into notes.

Sheeets does not contain an optical music recognition engine and is not going to
grow one: OMR is its own field, and the good implementations are years of work.
What lives here is the seam — how an engine is called, and what shape its answer
has to be in — plus drivers for two that exist (`engines.py`).

A recogniser is handed **one page image at a time** and returns the path to the
MusicXML it wrote.  Pages are joined afterwards by `score_xml.merge`, which
keeps the engines simple: none of them has to know that a part runs over ten
pages.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..model import Extraction


@runtime_checkable
class Recognizer(Protocol):
    @property
    def name(self) -> str: ...

    def available(self) -> bool: ...

    def recognize_page(self, image: Path, out_dir: Path) -> Path:
        """Read one page image; return the path of the MusicXML written."""


_REGISTRY: dict[str, Recognizer] = {}


def register(name: str, recognizer: Recognizer) -> None:
    _REGISTRY[name] = recognizer


def get_recognizer(name: str | None = None) -> Recognizer | None:
    if name:
        engine = _REGISTRY.get(name)
        return engine if engine is not None and engine.available() else None
    for engine in _REGISTRY.values():
        if engine.available():
            return engine
    return None


def available() -> list[str]:
    return sorted(name for name, engine in _REGISTRY.items() if engine.available())


def registered() -> list[str]:
    return sorted(_REGISTRY)


class ExternalRecognizer:
    """Any program that reads images from one folder and writes MusicXML to another.

    The command is a template with two placeholders, `{input}` and `{output}`.
    Set it with SHEEETS_OMR_COMMAND, e.g.

        SHEEETS_OMR_COMMAND="audiveris -batch -export -output {output} {input}"
    """

    def __init__(self, command: str | None = None, name: str = "external") -> None:
        self._explicit = command
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def command(self) -> str:
        # Read the environment when asked, not when constructed: the registry
        # builds one of these at import time, long before a caller has had the
        # chance to say where their OMR program lives.
        return self._explicit or os.environ.get("SHEEETS_OMR_COMMAND", "")

    def available(self) -> bool:
        if not self.command:
            return False
        return shutil.which(self.command.split()[0]) is not None

    def recognize_page(self, image: Path, out_dir: Path, timeout: int = 1800) -> Path:
        if not self.available():
            raise RuntimeError(
                "no OMR program configured; set SHEEETS_OMR_COMMAND to something "
                "that reads images from {input} and writes MusicXML to {output}"
            )
        image = Path(image)
        out_dir = Path(out_dir)
        in_dir = out_dir / f"{image.stem}-in"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(image, in_dir / image.name)
        command = self.command.format(input=str(in_dir), output=str(out_dir))
        subprocess.run(command, shell=True, check=True, timeout=timeout)
        produced = sorted(
            p for p in out_dir.rglob("*") if p.suffix.lower() in {".xml", ".musicxml"}
        )
        if not produced:
            raise RuntimeError(f"{command!r} wrote no MusicXML into {out_dir}")
        return produced[0]


def recognize_extraction(engine: Recognizer, extraction: Extraction, workdir: Path) -> str:
    """Read every piece of an extraction and return one merged MusicXML document."""
    from ..export.images import ImageExporter
    from ..score_xml import merge

    workdir = Path(workdir)
    images = workdir / "images"
    ImageExporter().write(extraction, images)
    pages = sorted(images.glob("*.png"))
    produced = [engine.recognize_page(page, workdir / "xml") for page in pages]
    tree = merge(produced, part_name=extraction.part_name)
    from xml.etree import ElementTree as ET

    return ET.tostring(tree.getroot(), encoding="unicode")


register("external", ExternalRecognizer())

from . import engines  # noqa: E402,F401  (registers oemer and audiveris)

__all__ = [
    "Recognizer", "ExternalRecognizer", "register", "get_recognizer",
    "available", "registered", "recognize_extraction",
]
