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
    """Give the file our page and staff size, and take away the score's.

    musicxml2ly writes its own `\paper` block and its own
    `#(set-global-staff-size)`, both derived from the *source* document — which
    here is a scan of a nineteen-stave conductor's score.  So a part engraved
    without this came out on a 41.6 x 30.0 cm sheet at staff size 14.5, with all
    388 measures crammed onto one landscape page, and a 3.2 cm indent on the
    first system.  Those settings are inherited furniture, not choices; strip
    them and put ours in their place.
    """
    source = _drop_lines(source, "#(set-global-staff-size")
    source = _drop_block(source, "\\paper")
    # musicxml2ly labels every system after the first with a short instrument
    # name it invents ("Voice") when the MusicXML has no part-abbreviation.  A
    # part is one instrument; it does not need its name down the margin.
    source = _drop_lines(source, "\\set Staff.shortInstrumentName")
    source = _drop_lines(source, "\\set DrumStaff.shortInstrumentName")
    source = _drop_lines(source, "\\set PianoStaff.shortInstrumentName")

    block = [
        f"#(set-global-staff-size {staff_size:g})",
        f'#(set-default-paper-size "{paper}"{" (quote landscape)" if landscape else ""})',
        "\\paper {",
        "    indent = 1.2\\cm",
        "    short-indent = 0\\cm",
        "    ragged-last-bottom = ##t",
        "}",
    ]
    match = re.search(r'^\\version\s+"[^"]+"\s*$', source, flags=re.M)
    if not match:
        return "\n".join(block) + "\n" + source
    at = match.end()
    return source[:at] + "\n" + "\n".join(block) + source[at:]


def _drop_lines(source: str, prefix: str) -> str:
    return "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith(prefix))


def _drop_block(source: str, keyword: str) -> str:
    """Remove `keyword { ... }`, counting braces so a nested one cannot fool it."""
    match = re.search(re.escape(keyword) + r"\s*\{", source)
    if not match:
        return source
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[: match.start()] + source[index + 1 :]
    return source
