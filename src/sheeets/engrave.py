"""Setting recognised music again, from scratch.

MusicXML is data; a PDF somebody can read from a stand is typography.  LilyPond
does the second half, and `musicxml2ly` (which ships with it) bridges the two.

The wrapper exists to keep three decisions in one place: the staff size, the
paper, and the titling.  Titles are set in the MusicXML rather than patched into
the LilyPond afterwards, because musicxml2ly builds its own `\\header` from the
score's `work-title` and `creator` and would overwrite anything written by hand.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Engraved:
    pdf: Path
    lilypond: Path
    log: str


class LilyPondEngraver:
    """Turn MusicXML into a freshly engraved PDF."""

    def __init__(self, lilypond: str = "lilypond", musicxml2ly: str = "musicxml2ly") -> None:
        self.lilypond = lilypond
        self.musicxml2ly = musicxml2ly

    @property
    def name(self) -> str:
        return "lilypond"

    def available(self) -> bool:
        return bool(shutil.which(self.lilypond) and shutil.which(self.musicxml2ly))

    def version(self) -> str:
        if not shutil.which(self.lilypond):
            return ""
        out = subprocess.run([self.lilypond, "--version"], capture_output=True, text=True)
        return out.stdout.splitlines()[0] if out.stdout else ""

    def engrave(
        self,
        musicxml: str | Path,
        out_pdf: str | Path,
        staff_size: float = 20.0,
        paper: str = "a4",
        landscape: bool = False,
        timeout: int = 600,
    ) -> Engraved:
        if not self.available():
            raise RuntimeError(
                "LilyPond is not installed (needs `lilypond` and `musicxml2ly` on PATH)"
            )
        musicxml = Path(musicxml)
        out_pdf = Path(out_pdf)
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        ly = out_pdf.with_suffix(".ly")

        first = subprocess.run(
            [self.musicxml2ly, "--output", str(ly), str(musicxml)],
            capture_output=True, text=True, timeout=timeout,
        )
        if not ly.exists():
            raise RuntimeError(f"musicxml2ly wrote nothing:\n{first.stderr[-2000:]}")

        ly.write_text(_with_layout(ly.read_text(encoding="utf-8"), staff_size, paper, landscape),
                      encoding="utf-8")

        second = subprocess.run(
            [self.lilypond, "-dno-point-and-click", "-o", str(out_pdf.with_suffix("")), str(ly)],
            capture_output=True, text=True, timeout=timeout,
        )
        if not out_pdf.exists():
            raise RuntimeError(f"lilypond wrote no PDF:\n{second.stderr[-2000:]}")
        return Engraved(pdf=out_pdf, lilypond=ly, log=first.stderr + second.stderr)


def _with_layout(source: str, staff_size: float, paper: str, landscape: bool) -> str:
    """Put the size and paper in, after the \\version line musicxml2ly writes."""
    block = [
        f'#(set-global-staff-size {staff_size:g})',
        f'#(set-default-paper-size "{paper}"{" (quote landscape)" if landscape else ""})',
    ]
    match = re.search(r'^\\version\s+"[^"]+"\s*$', source, flags=re.M)
    if not match:
        return "\n".join(block) + "\n" + source
    at = match.end()
    return source[:at] + "\n" + "\n".join(block) + source[at:]
