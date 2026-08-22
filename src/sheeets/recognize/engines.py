"""The optical music recognition engines Sheeets knows how to drive.

None of them is bundled — each is a program somebody else wrote, found on PATH
or pointed at with an environment variable.  What is written here is only how to
call it and where its answer lands:

    SHEEETS_OEMER       path to the `oemer` executable
    SHEEETS_AUDIVERIS   path to the Audiveris launcher script
    SHEEETS_OMR_COMMAND a command template, for anything else

Both engines are given **a page of the extracted part**, not the original score
and not a single strip.  A strip is too small — oemer works out its scale from
the staves it can see and divides by zero on one line of music.  The original
score is the wrong question: the point of the part is that the other eighteen
staves are gone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from . import register


class OemerRecognizer:
    """https://github.com/BreezeWhite/oemer — end-to-end neural OMR, Python.

    Fast to install and it will read anything, but it assumes a piano score: it
    returns a grand staff with a treble and a bass clef whatever it was given,
    so a one-staff part comes back with an empty staff attached and percussion
    comes back as pitches.  Useful as a draft; see NOTES.md for what it did to
    the percussion part.
    """

    def __init__(self, command: str | None = None) -> None:
        self._explicit = command

    @property
    def name(self) -> str:
        return "oemer"

    @property
    def command(self) -> str:
        return self._explicit or os.environ.get("SHEEETS_OEMER", "oemer")

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def recognize_page(self, image: Path, out_dir: Path, timeout: int = 1800) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [self.command, str(image), "-o", str(out_dir)],
            check=True, capture_output=True, text=True, timeout=timeout,
        )
        produced = out_dir / f"{Path(image).stem}.musicxml"
        if not produced.exists():
            raise RuntimeError(f"oemer wrote no MusicXML for {image.name}")
        return produced


class AudiverisRecognizer:
    """https://github.com/Audiveris/audiveris — the established open-source OMR.

    Slower, needs Java and Tesseract, and has to be built; in exchange it reads
    a single staff as a single staff, keeps multi-bar rests, and exports
    compressed MusicXML (.mxl), which is unzipped here.
    """

    def __init__(self, command: str | None = None) -> None:
        self._explicit = command

    @property
    def name(self) -> str:
        return "audiveris"

    @property
    def command(self) -> str:
        return self._explicit or os.environ.get("SHEEETS_AUDIVERIS", "audiveris")

    def available(self) -> bool:
        command = self.command
        return bool(shutil.which(command) or Path(command).is_file())

    def recognize_page(self, image: Path, out_dir: Path, timeout: int = 1800) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [self.command, "-batch", "-export", "-output", str(out_dir), "--", str(image)],
            check=True, capture_output=True, text=True, timeout=timeout,
        )
        return _unpack(out_dir, Path(image).stem)


def _unpack(out_dir: Path, stem: str) -> Path:
    """Audiveris writes <stem>.mxl (a zip) into a folder named after the input."""
    plain = sorted(out_dir.rglob(f"{stem}*.musicxml")) + sorted(out_dir.rglob(f"{stem}*.xml"))
    if plain:
        return plain[0]
    packed = sorted(out_dir.rglob(f"{stem}*.mxl"))
    if not packed:
        raise RuntimeError(f"audiveris wrote nothing for {stem} in {out_dir}")
    target = out_dir / f"{stem}.musicxml"
    with zipfile.ZipFile(packed[0]) as archive:
        # A .mxl holds META-INF/container.xml naming the real score; the score
        # is the only other .xml in there, so take that.
        names = [n for n in archive.namelist()
                 if n.lower().endswith((".xml", ".musicxml")) and "META-INF" not in n]
        if not names:
            raise RuntimeError(f"{packed[0]} contains no score")
        target.write_bytes(archive.read(names[0]))
    return target


register("audiveris", AudiverisRecognizer())
register("oemer", OemerRecognizer())
