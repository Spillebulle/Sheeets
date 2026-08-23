"""Finding the words printed around a staff — and not pretending to read them.

"S.Dr.", "+ B.Dr.", "+ C. Cym.", "solo" — a percussion part without them says
which rhythms to play and not which drum to play them on.  The extracted part
keeps them because it keeps the paper.  The retyped one cannot: measured on
this score, Audiveris's text step returned exactly one word from twenty-seven
pages of a nineteen-stave conductor's score, "Presto".

Reading them was tried, failed, and now works, and both halves of that are
worth keeping.

The first attempt got **three** answers out of ninety-eight runs of text and
two of the three were rubbish — "Y of", "JJI" — against one truncated "Cym".
Rendering at 600 dpi instead of 300 changed nothing, and the conclusion drawn
was that the limit was the size of the print.  It was not.  Two things were
wrong with the method.  It voted three tesseract *page-segmentation modes*
against each other and required them to agree, but only `--psm 7`, the
single-line mode, suits a two-word label; `--psm 13` returns noise on a crop
this small and outvoted the mode that was right.  And it asked an open
question — "what does this say?" — of print that gives nothing back to check
an answer against.

A part can only be asked to play a *known* thing.  "Which of these two dozen
markings is this, and how close?" is a far easier question, and the closeness
is itself the filter.  Measured on a score page where the answers are known:
"+ C. Cym." and "Tri." both match at 1.00, while the four hairpin and slur
ends the finder also picked up score 0.50, 0.50, 0.40 and 0.40.  Nothing sits
between, so `LIKENESS` is set at 0.80 and a marking is named or left alone.

What cannot be vouched for keeps its old behaviour: a position, mapped to a
bar, in the list of markings the fresh part could not carry.  That was always
a true and useful statement, and it is what a marking outside the vocabulary
still gets.  A part that names the wrong drum is worse than one that names
none.
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Marking:
    """A run of text-sized ink beside the staff: where it is, and — where the
    vocabulary can vouch for it — what it says."""

    x: int
    above: bool
    x1: int = 0
    top: int = 0
    bottom: int = 0
    text: str = ""


def find(image: np.ndarray, staff, threshold: int = 160,
         reach: float = 3.4) -> list[Marking]:
    """Every run of text-sized ink in the bands either side of one staff.

    Text is told from music by size and by company: a letter is between half a
    staff space and two, and letters come in runs.  A single blob that wide
    apart from its neighbours is a dynamic or a staccato dot, and is left out —
    the engine reads dynamics well enough, and it is the words it misses.
    """
    from scipy import ndimage

    space = float(staff.space)
    if space <= 0:
        return []
    out: list[Marking] = []
    for above, y0, y1 in (
        (True, staff.top - reach * space, staff.top - 0.4 * space),
        (False, staff.bottom + 0.5 * space, staff.bottom + reach * space),
    ):
        top, bottom = max(0, int(y0)), min(image.shape[0], int(y1))
        if bottom - top < 4:
            continue
        labels, _ = ndimage.label(image[top:bottom] < threshold,
                                  structure=np.ones((3, 3), dtype=int))
        pieces = []
        for slices in ndimage.find_objects(labels):
            if slices is None:
                continue
            ys, xs = slices
            height, width = ys.stop - ys.start, xs.stop - xs.start
            if 0.45 * space <= height <= 2.2 * space and 0.1 * space <= width <= 3.0 * space:
                pieces.append((int(xs.start), int(xs.stop),
                               int(ys.start), int(ys.stop)))
        if not pieces:
            continue
        pieces.sort()
        runs = [list(pieces[0])]
        for x0, x1, y0, y1 in pieces[1:]:
            if x0 - runs[-1][1] <= 1.1 * space:      # one phrase, not one letter
                runs[-1][1] = max(runs[-1][1], x1)
                runs[-1][2] = min(runs[-1][2], y0)
                runs[-1][3] = max(runs[-1][3], y1)
            else:
                runs.append([x0, x1, y0, y1])
        # The run's own rows, not the whole band.  A band three staff spaces
        # deep can hold a ledger-line notehead under the words, and tesseract's
        # single-line mode reads the two together and returns neither: "Tri."
        # with a note below it came back as "ie".
        out.extend(Marking(x0, above, x1=x1, top=top + y0, bottom=top + y1)
                   for x0, x1, y0, y1 in runs if x1 - x0 >= 1.5 * space)
    return out


# What a part is allowed to be told to play, and the spellings that mean the
# same thing.  This list is the whole reason the words can be read at all: two-
# and three-letter abbreviations at this size are past tesseract on their own,
# but "is this one of two dozen known things, and which?" is a far easier
# question than "what does this say".
#
# The aliases are not politeness.  "S. Dr." and "Bass Dr." are four characters
# apart, and on a real page a misread "ff" in front of "S.Dr." made "as S.Dr.,"
# — which scores 0.91 against "Bass Dr." and would have printed the wrong drum
# over the bar.  One entry per instrument, matched on its shortest spelling,
# keeps the near-misses from competing with each other.
KNOWN: dict[str, tuple[str, ...]] = {
    "S. Dr.": ("S.Dr.", "Sn.Dr.", "Side Dr.", "Snare Dr.", "Snare Drum"),
    "B. Dr.": ("B.Dr.", "Bass Dr.", "Bass Drum", "Gr.Cassa"),
    "T. Dr.": ("T.Dr.", "Ten.Dr.", "Tenor Drum"),
    "C. Cym.": ("C.Cym.", "Cr.Cym.", "Crash Cym."),
    "Cym.": ("Cymbals", "Piatti"),
    "Susp. Cym.": ("S.Cym.", "Sus.Cym.", "Susp.Cymbal"),
    "Tri.": ("Trgl.", "Triangle"),
    "Tamb.": ("Tambourine", "Tamburino"),
    "Tam-tam": ("Tamtam",),
    "Gong": (),
    "Timp.": ("Timpani",),
    "Glock.": ("Glockenspiel", "Glsp."),
    "Xyl.": ("Xylophone",),
    "Vib.": ("Vibraphone",),
    "Wood Bl.": ("W.Bl.", "Wood Block"),
    "Temple Bl.": ("Temple Blocks",),
    "Cast.": ("Castanets",),
    "Bells": ("Tubular Bells", "Chimes"),
    "Cowbell": (),
    "Whip": ("Slapstick",),
    "Ratchet": (),
    "Sleigh Bells": ("Slgh.Bells",),
    "solo": (),
    "tutti": (),
    "muta": (),
    "con sord.": (),
    "senza sord.": (),
}

# How close a reading has to be to one of them.  Measured over two parts where
# the right answers are known: **every** correct naming came in at 1.00 —
# "solo" seven times, "C. Cym.", "S. Dr.", "Tri.", "Cym." — and every wrong one
# at 0.80 or below.  There is no case in the measurement of a true reading
# between the two, so the line goes above 0.80 rather than in the middle.
LIKENESS = 0.85

# Enlargements to read at.  A short label wants tesseract's single-line mode,
# and the older attempt at this failed by voting three *modes* against each
# other: `--psm 13` returns rubbish on a crop this small and outvoted the mode
# that was right.  Voting scales under one mode, and letting the vocabulary
# pick the winner, reads "+ C. Cym." and "Tri." off the page that beat it.
HEIGHTS = (65, 100, 132)

# Words at most, per candidate phrase.  A label is one or two words and it can
# arrive with a dynamic swept in beside it, so every run of adjacent words is
# offered to the vocabulary and the best one wins.
PHRASE = 2

# The shortest reading worth offering to the vocabulary.  **Three**, and this
# is the setting the whole idea lives or dies on.
#
# It was two for an afternoon, to rescue a "Tri." that tesseract returned as
# "Ti." — 0.80, and no junk in the sample reached that.  The sample was one
# part.  On the *timpani* part the same setting put "T. Dr.", "B. Dr.",
# "Cym.", "S. Dr.", "Tri.", "Vib." and "Xyl." onto a part that has none of
# them, every one of them scoring exactly 0.80 off a two-letter read of
# something that is not a word at all: "(tr)" — the trill sign — reads as
# "tr", which is four fifths of "Tri.", and a stem and a hairpin read as "BD"
# and "cy".  A part that names the wrong drum is worse than one that names
# none, and this was that fault, shipped.
#
# Two letters cannot carry a name.  At three, every false naming in the
# measurement disappears and one true one is lost.
SHORTEST = 3


def _key(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


_KEYS: list[tuple[str, str]] = [
    (name, _key(spelling))
    for name, aliases in KNOWN.items()
    for spelling in (name, *aliases)
]


# What else is printed beside a staff, so that the nearest neighbour to a
# reading can be *nothing*.  A closed vocabulary only works if it is closed on
# both sides: "tr" is not far from "Tri." and it is on nearly every page of a
# timpani part.
NOT_A_MARKING = (
    "tr", "cresc.", "dim.", "decresc.", "poco", "molto", "rall.", "ritard.",
    "accel.", "sim.", "loco", "8va", "8vb", "sfz", "sffz", "fz", "rfz",
    "colla parte", "Presto", "Allegro", "Andante", "Adagio", "Largo",
    "Vivace", "Moderato", "Piu mosso", "Meno mosso", "Tempo I",
)

_STOPS = [_key(word) for word in NOT_A_MARKING]


def likeness(text: str) -> tuple[str, float]:
    """The known marking this reading is closest to, and how close.

    Every run of up to `PHRASE` adjacent words is tried, not the whole line:
    the finder's window is opened wide enough to hold the whole label and that
    lets a neighbouring dynamic in with it.  "as S.Dr.," read whole is closest
    to "Bass Dr."; read a word at a time it is exactly "S. Dr.".
    """
    words = [w for w in text.split() if _key(w)]
    if not words:
        return "", 0.0
    tries: list[str] = []
    for size in range(1, PHRASE + 1):
        for at in range(len(words) - size + 1):
            tries.append(" ".join(words[at:at + size]))
    best, score, seen_len = "", 0.0, 0
    for attempt in tries:
        seen = _key(attempt).lstrip("0123456789")
        if len(seen) < SHORTEST:
            continue
        for name, spelling in _KEYS:
            ratio = difflib.SequenceMatcher(None, seen, spelling).ratio()
            # On a tie the longer reading wins: "+C. Cym." matches both
            # "C. Cym." and "Cym." exactly, and it is the crash cymbal.
            if (ratio, len(seen)) > (score, seen_len):
                best, score, seen_len = name, ratio, len(seen)
        for stop in _STOPS:
            ratio = difflib.SequenceMatcher(None, seen, stop).ratio()
            if (ratio, len(seen)) > (score, seen_len):
                best, score, seen_len = "", ratio, len(seen)
    return best, score


def read(image: np.ndarray, markings: list[Marking], space: float,
         least: float = LIKENESS) -> list[Marking]:
    """Name the markings that the vocabulary can vouch for; leave the rest.

    A part that names the wrong drum is worse than one that names none, so a
    reading is only kept when it is close to something a part can actually be
    asked to play.  Everything else keeps its position and stays in the list
    of markings the fresh part could not carry.
    """
    if not shutil.which("tesseract") or space <= 0:
        return markings
    out: list[Marking] = []
    here = _merge(markings, space)
    with tempfile.TemporaryDirectory(prefix="sheeets-words-") as tmp:
        for n, mark in enumerate(here):
            after = next((m.x for m in here[n + 1:] if m.above == mark.above), None)
            crop = _crop(image, mark, space, after)
            if crop is None:
                out.append(mark)
                continue
            best, score = _vote(_readings(crop, Path(tmp) / f"w{n}.png"))
            out.append(replace(mark, text=best) if score >= least else mark)
    return out


def _vote(readings: list[str]) -> tuple[str, float]:
    """The marking the enlargements agree on, and the best score it got.

    Two of the three have to point at the same thing.  Measured across the
    fleet's thirty-three namings, the one that was plainly wrong — a notehead
    and a slur named "Gong" — is the only one carried by a single reading:
    tesseract saw "Gon" at one enlargement and nothing at the other two.  A
    true naming is agreed on even where only one enlargement reads it well,
    because the vocabulary pulls the poor readings to the same word: "Gyms.",
    "Gyms." and "Cyms." are 0.57, 0.57 and 0.86 against *Cym.* and all three
    name it.

    Supporters first, then the score, so the agreed word wins over a better
    match that stands alone.
    """
    by_name: dict[str, list[float]] = {}
    for reading in readings:
        name, ratio = likeness(reading)
        if name:
            by_name.setdefault(name, []).append(ratio)
    if not by_name:
        return "", 0.0
    name = max(by_name, key=lambda k: (len(by_name[k]), max(by_name[k])))
    if len(by_name[name]) < 2:
        return "", 0.0
    return name, max(by_name[name])


def _merge(markings: list[Marking], space: float) -> list[Marking]:
    """One marking per phrase.  The finder splits on a gap of a staff space,
    which puts "+ C." and "Cym." in two boxes and reads the second alone."""
    out: list[Marking] = []
    for mark in sorted(markings, key=lambda m: (not m.above, m.x)):
        last = out[-1] if out else None
        if (last is not None and last.above == mark.above
                and mark.x - last.x1 <= 2.5 * space):
            out[-1] = replace(last, x1=max(last.x1, mark.x1))
        else:
            out.append(mark)
    return out


def _crop(image: np.ndarray, mark: Marking, space: float,
          after: int | None = None) -> np.ndarray | None:
    """The window to read, which is wider than the ink the finder measured.

    The finder joins letters into a run and stops at a gap, and a gap is
    exactly what a full stop leaves: "Tri." came back as twenty-seven pixels
    of "T" and read as "ie".  Text runs left to right, so the window is opened
    to the right as far as the next marking in the same band, or eight staff
    spaces — a line of white costs tesseract nothing and a truncated word
    costs it the answer.
    """
    pad = int(0.6 * space)
    x0 = max(0, mark.x - pad)
    reach = int(mark.x + 8 * space)
    if after is not None:
        reach = min(reach, int(after - 0.4 * space))
    x1 = min(image.shape[1], max((mark.x1 or mark.x) + pad, reach))
    grow = max(1, int(0.15 * space))
    top = max(0, mark.top - grow)
    bottom = min(image.shape[0], mark.bottom + grow)
    if x1 - x0 < 4 or bottom - top < 6:
        return None
    return image[top:bottom, x0:x1]


def _readings(crop: np.ndarray, path: Path) -> list[str]:
    from PIL import Image

    out: list[str] = []
    picture = Image.fromarray(crop).convert("L")
    for target in HEIGHTS:
        scale = max(1, round(target / max(1, picture.height)))
        big = picture.resize((picture.width * scale, picture.height * scale),
                             Image.LANCZOS)
        canvas = Image.new("L", (big.width + 40, big.height + 40), 255)
        canvas.paste(big, (20, 20))
        canvas.save(path)
        result = subprocess.run(["tesseract", str(path), "stdout", "--psm", "7"],
                                capture_output=True, text=True)
        if result.returncode == 0:
            out.append(" ".join(result.stdout.split()))
    return out
