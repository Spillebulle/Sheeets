"""Turning pixels into notes — the part that is deliberately not written yet.

Optical music recognition is its own project, and pretending otherwise would put
a lie in the ledger.  What lives here is the seam: a `Recognizer` takes the
segments a run produced and returns MusicXML.  Nothing in the pipeline calls one
unless asked, and if nobody has registered one, the MusicXML exporter says so in
a sentence instead of writing an empty file.

`ExternalRecognizer` covers the realistic case — an OMR program (Audiveris,
oemer, PhotoScore) that reads images and writes MusicXML — by running it as a
subprocess.  Point it at the command and it works; there is no bundled engine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from ..model import Extraction


@runtime_checkable
class Recognizer(Protocol):
    @property
    def name(self) -> str: ...

    def available(self) -> bool: ...

    def recognize(self, extraction: Extraction, workdir: Path) -> str:
        """Return MusicXML for the extracted part."""


_REGISTRY: dict[str, Recognizer] = {}


def register(name: str, recognizer: Recognizer) -> None:
    _REGISTRY[name] = recognizer


def get_recognizer(name: str | None = None) -> Recognizer | None:
    if name:
        return _REGISTRY.get(name)
    for rec in _REGISTRY.values():
        if rec.available():
            return rec
    return None


def available() -> list[str]:
    return sorted(n for n, r in _REGISTRY.items() if r.available())


class ExternalRecognizer:
    """Run an OMR program over the extracted images.

    The command is a template with two placeholders: `{input}` is a folder of
    PNGs, one per piece, in playing order, and `{output}` is a folder the tool
    should write MusicXML into.  Set it with SHEEETS_OMR_COMMAND, e.g.

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

    def recognize(self, extraction: Extraction, workdir: Path) -> str:
        if not self.available():
            raise RuntimeError(
                "no OMR program configured; set SHEEETS_OMR_COMMAND to something "
                "that reads images from {input} and writes MusicXML to {output}"
            )
        from ..export.images import ImageExporter

        workdir = Path(workdir)
        in_dir = workdir / "input"
        out_dir = workdir / "output"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        ImageExporter().write(extraction, in_dir)

        command = self.command.format(input=str(in_dir), output=str(out_dir))
        subprocess.run(command, shell=True, check=True)

        produced = sorted(
            p for p in out_dir.rglob("*") if p.suffix.lower() in {".xml", ".musicxml"}
        )
        if not produced:
            raise RuntimeError(f"{command!r} wrote no MusicXML into {out_dir}")
        return produced[0].read_text(encoding="utf-8")


register("external", ExternalRecognizer())

__all__ = ["Recognizer", "ExternalRecognizer", "register", "get_recognizer", "available"]
