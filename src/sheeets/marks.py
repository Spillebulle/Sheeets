"""Rehearsal marks — found by looking for the box, not by reading the page.

A conductor's score prints its rehearsal letters once, in a box above the top
staff, and nowhere else.  Cut a part out of the bottom of the system and they
are gone; a band part without rehearsal letters is close to useless at a
rehearsal, so they have to be brought across.

The OMR engine does not find them here.  Given a nineteen-stave page at 300 dpi
its text step returned "Presto", "solo", and a handful of mangled fragments —
not one of the boxed letters.  But a rehearsal mark is the most geometrically
distinctive thing on the page: a hollow rectangle, two to five staff spaces on a
side, sitting above the top staff with a single character inside it.  Measured
on this score, the box for "A" scores 0.71 ink around its border and 0.04
inside, where nothing else in that band comes close.

So the box is found by shape and only its *contents* are handed to OCR, one
character at a time, which is a far easier question than reading a whole page.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Mark:
    """A rehearsal mark: what it says, and where on the page it says it."""

    text: str
    x: int
    y: int
    width: int
    height: int

    @property
    def centre_x(self) -> int:
        return self.x + self.width // 2


def find_boxes(
    image: np.ndarray,
    top_row: int,
    space: float,
    reach_spaces: float = 12.0,
    threshold: int = 215,
    tall: float = 2.4,
    gap: tuple[float, float] = (1.2, 5.8),
    edge_ink: float = 0.85,
    inner_ink: float = 0.55,
) -> list[tuple[int, int, int, int]]:
    """Rectangles in the band above a staff, found from their four strokes.

    Returns (x, y, w, h), left to right.

    The obvious way — one connected component whose border is inked and whose
    middle is not — cannot do this, and the reason is worth keeping. On a
    publisher's part the frames are printed **grey**: measured on one, no pixel
    of a rehearsal box is darker than 100 and most of the frame is lighter than
    160. At a threshold tight enough to separate the box from the music the
    frame arrives in pieces (the "J" box came out as a 25 x 40 fragment scoring
    0.13 where 0.30 was wanted); at one generous enough to catch the whole
    frame the box joins the ties and the bar number beside it and the component
    is the width of the system. Eight of that part's fifteen boxes were found
    and three of the eight read; five were rubbish.

    A rectangle is not a blob, though — it is **two tall vertical strokes of
    the same height, closed top and bottom, with white between them**, and that
    description survives the generous threshold intact. Taking the longest
    vertical run in each column of the band picks the sides out exactly: on the
    band holding J, K and L, seventeen columns of 2480 carry a run of three
    staff spaces, and they are the six box sides and nothing else.

    Then the tests are on the *pair*: same height, a plausible gap, ink along
    all four edges, white in the middle. On the same part this finds **fifteen
    boxes of fifteen — A to O, in order, with nothing spurious.**

    `inner_ink` is 0.55 and not the 0.22 the first version used: a capital
    letter at this size fills a third to a half of the space inside its frame.
    The four edges are what makes this specific; the middle only has to not be
    solid.
    """
    y1 = max(0, int(top_row) - 2)
    y0 = max(0, int(top_row - reach_spaces * space))
    if y1 - y0 < 4 or space <= 0:
        return []
    band = image[y0:y1]
    ink = band < threshold
    height, width = ink.shape
    least = int(tall * space)
    if height < least + 2 or width < 8:
        return []

    runs, starts = _down_runs(ink)
    sides: list[tuple[int, int, int, int]] = []
    x = 0
    while x < width:
        if runs[x] < least:
            x += 1
            continue
        wide = x
        while (wide + 1 < width and runs[wide + 1] >= least
               and abs(int(starts[wide + 1]) - int(starts[x])) <= 3):
            wide += 1
        here = slice(x, wide + 1)
        sides.append((x, wide, int(starts[here].min()),
                      int((starts[here] + runs[here]).max())))
        x = wide + 1

    out: list[tuple[int, int, int, int]] = []
    for i, left in enumerate(sides):
        for right in sides[i + 1:]:
            if not gap[0] * space <= right[0] - left[1] <= gap[1] * space:
                continue
            over0, over1 = max(left[2], right[2]), min(left[3], right[3])
            longest = max(left[3] - left[2], right[3] - right[2])
            if over1 - over0 < least or over1 - over0 < 0.85 * longest:
                continue
            box = ink[over0:over1, left[0]:right[1] + 1]
            h, w = box.shape
            if h < 6 or w < 6:
                continue
            # The *best* line near each edge, not the average of a band of
            # them. A frame is one or two pixels thick however big the box is,
            # so averaging over h/20 rows asks a 43-pixel box on a score page
            # to have a frame twice as thick as it has: measured, that cost
            # ten of the score's twenty-two boxes while costing the
            # publisher's part, whose staves are two thirds larger, none.
            cap, post = max(2, h // 10), max(2, w // 10)
            if min(box[:cap].mean(axis=1).max(), box[-cap:].mean(axis=1).max(),
                   box[:, :post].mean(axis=0).max(),
                   box[:, -post:].mean(axis=0).max()) < edge_ink:
                continue
            margin = max(2, min(h, w) // 6)
            inside = box[margin:-margin, margin:-margin]
            if inside.size and inside.mean() > inner_ink:
                continue
            out.append((int(left[0]), int(y0 + over0), int(w), int(h)))
    return sorted(out)


def _down_runs(ink: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For every column: its longest run of ink, and where that run starts."""
    height, width = ink.shape
    best = np.zeros(width, np.int32)
    where = np.zeros(width, np.int32)
    running = np.zeros(width, np.int32)
    began = np.zeros(width, np.int32)
    for row in range(height):
        here = ink[row]
        running = np.where(here, running + 1, 0)
        began = np.where(here & (running == 1), row, began)
        longer = running > best
        where = np.where(longer, began, where)
        best = np.maximum(best, running)
    return best, where


def read_box(image: np.ndarray, box: tuple[int, int, int, int], pad: int = 3) -> str:
    """OCR the inside of one box: a single letter or number.

    Deliberately plain, and it was made less plain once and put back.  Two
    apparently better ideas — isolating the letter from the frame by connected
    components, and enlarging it to about 150 px before reading — were tried
    against the twenty-two boxes of this score, where the right answer is
    known: the plain crop reads a run of A to O and each clever version breaks
    it, turning C into K or D into G.  Tesseract is doing its own thresholding
    and layout work on what it is handed, and handing it a tight, resampled
    glyph takes that away.

    So: the inside of the box, at its own size, with white around it.
    """
    if not shutil.which("tesseract"):
        return ""
    x, y, w, h = box
    inside = image[y + pad : y + h - pad, x + pad : x + w - pad]
    if inside.size == 0:
        return ""
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="sheeets-mark-") as tmp:
        path = Path(tmp) / "mark.png"
        # Tesseract does better with room around the glyph than with a tight crop.
        canvas = Image.new("L", (inside.shape[1] + 40, inside.shape[0] + 40), 255)
        canvas.paste(Image.fromarray(inside), (20, 20))
        canvas.save(path)
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "10",
             "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"],
            capture_output=True, text=True,
        )
    return result.stdout.strip().split("\n")[0].strip() if result.returncode == 0 else ""


def find_marks(image: np.ndarray, top_row: int, space: float, **kwargs) -> list[Mark]:
    """Every box in the band, with whatever could be read inside it.

    A box whose letter could not be read is **kept**, with an empty `text`.
    It used to be dropped, and that was right while the shape test was the
    generous half and OCR the strict one — but it is the other way round now.
    Measured on a publisher's part: fifteen boxes found, fifteen real, and
    fourteen letters read correctly. Dropping the fifteenth threw away the
    *position* of B, and a sequence with a hole in it cannot be checked. Kept,
    the run A–O closes over it and B goes in where the page has it.
    """
    return [Mark(text=read_box(image, box), x=box[0], y=box[1],
                 width=box[2], height=box[3])
            for box in find_boxes(image, top_row, space, **kwargs)]


# How many letters a run needs before it may begin somewhere other than "A".
# Six, and only with nothing corrected: a run every letter of which was read
# off the page cannot be shifted along the alphabet, so where it starts says
# only that the boxes before it were missed — but a short one is weak evidence
# either way, and the fault this guard was written for was a run of misreadings
# that happened to ascend.
LATE_START = 6


def tidy_sequence(texts: list[str]) -> tuple[list[str], list[str], list[int]]:
    """Keep the longest alphabetical chain and throw the rest away.

    Rehearsal letters run A, B, C … in page order.  That is a far stronger fact
    than any single OCR result at this size, where the classic confusions all
    bite — C read as G, O as zero, I as one, S as five — and where the box
    detector, made generous enough to catch a rehearsal box whose printed frame
    has broken, also picks up the odd rectangle that is not one.

    Both problems fall to the same treatment.  Find the longest run of items
    whose letters ascend by one in page order; that run is the real sequence.
    Anything outside it was never a rehearsal mark.  A gap inside it — B then
    D — is a letter misread, and if an unused item sits between them it is
    corrected to the letter its position demands.

    Returns the letters, a note of every change, and which of the original
    items were kept.
    """
    if len(texts) < 3:
        return list(texts), [], list(range(len(texts)))

    single = [t if len(t) == 1 and "A" <= t <= "Z" else "" for t in texts]
    best_length = [0] * len(texts)
    previous = [-1] * len(texts)
    for i, letter in enumerate(single):
        if not letter:
            continue
        best_length[i] = 1
        for j in range(i):
            if single[j] and ord(letter) - ord(single[j]) == 1 and best_length[j] + 1 > best_length[i]:
                best_length[i] = best_length[j] + 1
                previous[i] = j
    if not any(best_length):
        return [], _gave_up(texts), []

    end = max(range(len(texts)), key=lambda i: best_length[i])
    chain: list[int] = []
    while end != -1:
        chain.append(end)
        end = previous[end]
    chain.reverse()
    if len(chain) < 3:
        return [], _gave_up(texts), []

    notes: list[str] = []
    kept: list[int] = []
    letters: list[str] = []
    for n, index in enumerate(chain):
        if n:
            expected = chr(ord(single[chain[n - 1]]) + 1)
            # A letter missing from the chain: look for an item between the two
            # positions that can be corrected into it.
            while expected != single[index]:
                spare = next(
                    (k for k in range(chain[n - 1] + 1, index) if k not in kept),
                    None,
                )
                if spare is None:
                    break
                notes.append(
                    f"read {texts[spare]!r} where the sequence wants {expected!r}; corrected"
                )
                kept.append(spare)
                letters.append(expected)
                expected = chr(ord(expected) + 1)
        kept.append(index)
        letters.append(single[index])

    # The chain found by exact matches can start late: if the second mark was
    # misread, "A B" scores 2 against a clean "D..N" of eleven.  Reach outwards
    # from the chain into the items either side, which must be the letters
    # before and after it.
    # Reaching outwards must not overwrite a reading that is already good.
    # Measured on a publisher's part where the boxes are found exactly: the
    # chain ran C to O, the item before it read a clean "A", and the sequence
    # wanted "B" there — so it "corrected" the A, and the run then began at B
    # and was refused whole. The A was right; what was missing was B's box,
    # whose letter had not been read. A clean letter that is not the expected
    # one means a box was **missed**, not misread, so the sequence steps to it.
    expected = chr(ord(letters[0]) - 1)
    for index in range(min(kept) - 1, -1, -1):
        if index in kept or expected < "A":
            continue
        here = single[index]
        # Going backwards, a clean letter *below* the expectation cannot be the
        # expected one, and reading it as such would be a fabrication — so the
        # sequence steps down to it and the letters between were boxes that
        # were missed. A letter *above* it cannot belong further back at all,
        # so that one is a misreading and is corrected.
        if here and here < expected:
            expected = here
        if texts[index] != expected:
            notes.append(f"read {texts[index]!r} where the sequence wants {expected!r}; corrected")
        kept.insert(0, index)
        letters.insert(0, expected)
        expected = chr(ord(expected) - 1)

    expected = chr(ord(letters[-1]) + 1)
    for index in range(max(kept) + 1, len(texts)):
        if index in kept or expected > "Z":
            continue
        here = single[index]
        if here and here > expected:       # the mirror of the rule above
            expected = here
        if texts[index] != expected:
            notes.append(f"read {texts[index]!r} where the sequence wants {expected!r}; corrected")
        kept.append(index)
        letters.append(expected)
        expected = chr(ord(expected) + 1)

    # How much of this run was actually *read*, and how much was asserted?
    # The outward reach above takes an unused item and declares it the next
    # letter without looking at it, which is right when one box in a good run
    # was misread and catastrophic when the boxes are mostly noise.  Measured
    # on a publisher's timpani part with a generous box detector: twenty-six
    # candidates, four letters read correctly, and this returned a confident
    # A to Z.  A run that is mostly correction is not a reading of the page.
    corrected = sum(1 for note in notes if note.endswith("corrected"))
    if corrected * 3 > len(letters):
        return [], notes + [f"only {len(letters) - corrected} of {len(letters)} "
                            f"rehearsal letters could actually be read; the rest "
                            f"would have been invented, so none are used"], []
    if letters[0] != "A" and (corrected or len(letters) < LATE_START):
        # Rehearsal letters begin at A, and a run that starts anywhere else
        # used to be refused outright: it is what a pile of misreadings that
        # happen to ascend looks like, and placing it would put the wrong
        # letter over every bar it names.  Measured on a publisher's part with
        # a broken box detector, the longest ascending run of what could be
        # read was F to P over marks that are in fact A to O.
        #
        # But that run was nearly all *correction*, and that is the thing
        # actually worth refusing.  A run every letter of which was read off
        # the page cannot be shifted along the alphabet — each letter is the
        # letter it says it is — so where it begins says only that the boxes
        # before it were missed.  One page of the fleet reads a clean B to K,
        # ten letters, no corrections; refusing it placed nothing at all.
        return [], notes + [f"the letters read run from {letters[0]!r}, not from 'A', "
                            f"and it is not long enough or clean enough to be "
                            f"believed on its own; none are used"], []
    dropped = [texts[i] for i in range(len(texts)) if i not in kept]
    for text in dropped:
        notes.append(f"dropped {text!r}: not part of the run")
    return letters, notes, sorted(kept)


def _gave_up(texts: list[str]) -> list[str]:
    return [f"read {' '.join(t for t in texts if t)!r} above the staves, "
            f"which is not a run of rehearsal letters; none of them are used"]


def measure_of(mark: Mark, barlines: list[int]) -> int:
    """Which bar of the system a mark belongs to, counting from 0.

    A rehearsal mark sits over the barline that begins its bar, so the bar it
    marks is the one starting at or just before it.
    """
    if not barlines:
        return 0
    before = [i for i, x in enumerate(barlines) if x <= mark.centre_x + 4]
    return max(0, (before[-1] if before else 0))
