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

    def complaints(self) -> list[str]:
        """What LilyPond said about the music, in the app's own words.

        This is here because of a fault that was reported by the person
        reading the PDF and not by anything the app measured: a timpani part
        whose last system was 915 pt wide on a 595 pt page.  Every number the
        app printed was healthy — the right number of measures, the right
        number of bars, six flagged — and the cause had been sitting in
        LilyPond's log the whole time, one line saying `barcheck failed at:
        1/16`.  A bar check that fails means the barline grid is off from
        there on, which is not something a count of measures can see.

        So the engraver reports what the engraver knows.  Only the lines that
        mean the music is wrong are kept; LilyPond is talkative about
        typography and none of that belongs in a warning list.
        """
        out: list[str] = []
        checks = sorted({m for m in re.findall(r"barcheck failed at: (\S+)", self.log)})
        if checks:
            out.append(f"LilyPond: the barline grid is off — {len(checks)} bar check(s) "
                       f"failed, the first {checks[0]} into a bar")
        for pattern, say in (
            (r"warning: .*[Cc]lash", "LilyPond: notes or rests collide"),
            (r"warning: .*[Uu]nterminated", "LilyPond: a spanner is left open"),
            (r"warning: .*no viable initial configuration",
             "LilyPond: a beam or slur could not be drawn"),
            (r"programming error", "LilyPond: internal error — the PDF may be wrong"),
        ):
            hits = len(re.findall(pattern, self.log))
            if hits:
                out.append(f"{say} ({hits})")
        return out


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

        ly.write_text(
            _with_layout(ly.read_text(encoding="utf-8"), staff_size, paper, landscape,
                         systems=_systems_for(musicxml),
                         indent_cm=_indent_for(musicxml)),
            encoding="utf-8",
        )

        second = subprocess.run(
            [self.lilypond, "-dno-point-and-click", "-o", str(out_pdf.with_suffix("")), str(ly)],
            capture_output=True, text=True, timeout=timeout,
        )
        if not out_pdf.exists():
            raise RuntimeError(f"lilypond wrote no PDF:\n{second.stderr[-2000:]}")
        return Engraved(pdf=out_pdf, lilypond=ly, log=first.stderr + second.stderr)


def _systems_for(musicxml: Path, target_events: int = 20) -> int | None:
    """How many systems this part wants, or None to let LilyPond decide.

    LilyPond fills a line and then breaks it, which for a part of plain
    crotchets and whole-bar rests means it will happily put thirty bars on one
    line while an earlier line has five.  Measured on a timpani part: nine
    systems of five to eight bars, then one of about thirty with the
    multi-measure rests squeezed below their own minimum width and the numbers
    sitting on the staff.  There is no LilyPond setting for "bars per line";
    there is one for how many systems the whole part gets, and LilyPond then
    distributes them evenly, which is the same thing said from the other end.

    So the count is worked out here.  What matters is not bars but *how much is
    in* a bar, so the target is a number of written events to a line and the
    bars follow from it.  Twenty was read off the page: this timpani part
    averages 2.25 events to a bar and wants nine bars to a line, which is close
    to what the publisher's own engraving of it does.  A part of running
    semiquavers lands at four bars a line, which is also right.  Between four
    and twelve either way.

    This is a count, not a set of break points.  Putting the breaks in
    explicitly was tried — `<print new-system="yes">` every N bars, which
    musicxml2ly turns into a break — and it is worse: where a part has two
    voices, musicxml2ly pads the silent one with one long skip per run of empty
    bars, those runs do not line up with the other voice's multi-measure rests,
    and a break inside one leaves an empty staff line behind and prints the
    rest twice.  LilyPond has to be allowed to choose *where*; all it needs
    from here is how many.

    Multi-measure rests are counted as the one bar they are drawn as.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(musicxml).getroot()
    except Exception:
        return None
    part = root.find("part")
    if part is None:
        return None
    measures = part.findall("measure")
    hidden = 0
    for measure in measures:
        element = measure.find(".//multiple-rest")
        if element is not None and (element.text or "").strip().isdigit():
            hidden += max(0, int(element.text.strip()) - 1)
    drawn = len(measures) - hidden
    if drawn < 8:
        return None
    sounding = sum(
        1 for note in part.iter("note")
        if note.find("rest") is None or note.find("rest").get("measure") != "yes"
    )
    per_bar = max(1.0, sounding / drawn)
    per_line = min(12, max(4, round(target_events / per_bar)))
    return max(1, -(-drawn // per_line))


def _indent_for(musicxml: Path) -> float:
    """How much room the first system needs for the instrument's name.

    LilyPond does not grow the indent to fit the name; it draws the name to the
    left of the staff and lets it run off the paper.  "Optional Percussion"
    came out as "l Percussion" with the rest past the edge of the page.  At the
    default font a character is about 1.9 mm wide, so the indent follows from
    the name — floored at the 1.2 cm that looks right for a short one, and
    capped so a long one cannot eat the system.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(musicxml).getroot()
    except Exception:
        return 1.2
    names = [(n.text or "").strip() for n in root.iter("part-name")]
    longest = max((len(n) for n in names), default=0)
    return round(min(5.0, max(1.2, 0.6 + 0.19 * longest)), 2)


def _with_layout(source: str, staff_size: float, paper: str, landscape: bool,
                 systems: int | None = None, indent_cm: float = 1.2) -> str:
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
        f"    indent = {indent_cm:g}\\cm",
        "    short-indent = 0\\cm",
        "    ragged-last-bottom = ##t",
        # Let the last page end where the music does rather than spreading the
        # systems down it; a part is read from a stand, not admired.
        "    ragged-bottom = ##t",
    ]
    if systems:
        block.append(f"    system-count = {systems}")
    block.append("}")
    source = _plain_staff(source)
    source = _with_rest_shape(source)
    match = re.search(r'^\\version\s+"[^"]+"\s*$', source, flags=re.M)
    if not match:
        return "\n".join(block) + "\n" + source
    at = match.end()
    return source[:at] + "\n" + "\n".join(block) + source[at:]


# A multi-measure rest is the most important thing on a part's page and the
# thing LilyPond gives least room to by default: at this size a rest of eight
# bars came out barely wider than a crotchet, with its number pressed onto the
# staff between two barlines a few millimetres apart.  A player reads that
# number from a stand.
_REST_SHAPE = """
        \\override MultiMeasureRest.minimum-length = #16
        \\override MultiMeasureRest.space-increment = #3
        \\override MultiMeasureRestNumber.staff-padding = #1.2
        %% A rehearsal letter is printed in a box on the score it came from,
        %% and a player looks for the box rather than for the letter.
        \\override RehearsalMark.stencil = #(make-stencil-boxer 0.1 0.6 ly:text-interface::print)"""


def _plain_staff(source: str) -> str:
    """Take the part off LilyPond's DrumStaff and put it on an ordinary one.

    A part of unpitched noteheads makes musicxml2ly write `\\new DrumStaff` and
    `\\context DrumVoice` — and then fill them with ordinary pitches, because
    that is all the MusicXML holds.  A DrumStaff places notes by looking their
    *drum name* up in `drumStyleTable`; handed `f4` and `c'4` it has nothing to
    look up, so it puts them wherever it likes.  On the percussion part that
    meant the snare drum and the bass drum, which the scan prints on different
    lines, came out on the **same line** from bar 19 to the end.

    An ordinary Staff places a note by its pitch, which is exactly what
    Audiveris gives us: it reads *where on the staff* a notehead sits, not which
    drum it is.

    **And the clef has to place those pitches the way the reader did.**  This
    is the half that is easy to miss, because the staff looks right and the
    notes are simply in the wrong place.  LilyPond's `\\clef "percussion"` puts
    middle C on the middle line; Audiveris writes its display positions as a
    *treble* reader sees them.  Handed C5 and F4 under a percussion clef, both
    landed **above** the staff a step apart — where the page has them four
    steps apart and inside it.  Measured on the percussion part: with treble
    positioning the bass drum sits in the first space and the snare in the
    third, which is what the scan shows; with LilyPond's own the pair floats
    off the top.

    So the drawn glyph stays the neutral percussion clef, and only the pitch
    placement is moved back to where it was read.
    """
    for was, now in (("\\new DrumStaff", "\\new Staff"),
                     ("\\context DrumStaff", "\\context Staff"),
                     ("\\set DrumStaff.", "\\set Staff."),
                     ("\\context DrumVoice", "\\context Voice"),
                     ("\\new DrumVoice", "\\new Voice")):
        source = source.replace(was, now)
    return source.replace(
        '\\clef "percussion"',
        '\\clef "percussion" \\set Staff.middleCPosition = #-6'
        ' \\set Staff.middleCClefPosition = #-6',
    )


def _with_rest_shape(source: str) -> str:
    """Give multi-measure rests room, inside whatever Score context exists."""
    match = re.search(r"\\context\s*\{\s*\\Score", source)
    if not match:
        return source.replace(
            "\\score {",
            "\\layout {\n    \\context { \\Score" + _REST_SHAPE + "\n        }\n    }\n\n\\score {",
            1,
        )
    at = match.end()
    return source[:at] + _REST_SHAPE + source[at:]


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
