"""MusicXML out — by way of a recogniser, or not at all.

Kept as a real exporter so the rest of the program (and the command line) needs
no special case the day a recogniser exists.  Today it fails with a sentence
that says what is missing, which is the honest answer.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..model import Extraction
from ..recognize import get_recognizer
from . import register


class MusicXmlExporter:
    suffix = ".musicxml"

    def write(self, extraction: Extraction, path: Path, recognizer: str | None = None, **_) -> Path:
        engine = get_recognizer(recognizer)
        if engine is None:
            raise RuntimeError(
                "MusicXML needs an optical music recognition engine, and none is "
                "configured.  Export images or a PDF, or set SHEEETS_OMR_COMMAND "
                "(see sheeets.recognize) to a program that reads images and writes "
                "MusicXML."
            )
        with tempfile.TemporaryDirectory(prefix="sheeets-omr-") as tmp:
            xml = engine.recognize(extraction, Path(tmp))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding="utf-8")
        return path


register("musicxml", MusicXmlExporter())
