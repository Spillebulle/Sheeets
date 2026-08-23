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
    threshold: int = 160,
    min_side: float = 1.2,
    max_side: float = 7.0,
    border_ink: float = 0.30,
    inner_ink: float = 0.5,
) -> list[tuple[int, int, int, int]]:
    """Hollow rectangles in the band above a staff.  Returns (x, y, w, h)."""
    from scipy import ndimage

    y1 = max(0, int(top_row) - 2)
    y0 = max(0, int(top_row - reach_spaces * space))
    if y1 - y0 < 4:
        return []
    band = image[y0:y1] < threshold
    labels, _ = ndimage.label(band, structure=np.ones((3, 3), dtype=int))
    out: list[tuple[int, int, int, int]] = []
    for k, slices in enumerate(ndimage.find_objects(labels), start=1):
        if slices is None:
            continue
        ys, xs = slices
        height, width = ys.stop - ys.start, xs.stop - xs.start
        if not (min_side * space <= height <= max_side * space):
            continue
        if not (min_side * space <= width <= max_side * space):
            continue
        if not (0.5 <= width / height <= 2.0):
            continue
        piece = labels[slices] == k
        border = np.concatenate([piece[0], piece[-1], piece[:, 0], piece[:, -1]])
        inner = piece[2:-2, 2:-2]
        if border.mean() >= border_ink and inner.size and inner.mean() <= inner_ink:
            out.append((int(xs.start), int(y0 + ys.start), int(width), int(height)))
    return sorted(out)


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
    marks: list[Mark] = []
    for box in find_boxes(image, top_row, space, **kwargs):
        text = read_box(image, box)
        if text:
            marks.append(Mark(text=text, x=box[0], y=box[1], width=box[2], height=box[3]))
    return marks


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

    single = [t if len(t) == 1 and t.isalpha() else "" for t in texts]
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
                    (k for k in range(chain[n - 1] + 1, index)
                     if k not in kept and texts[k]),
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
    first_letter = letters[0]
    expected = chr(ord(first_letter) - 1)
    for index in range(min(kept) - 1, -1, -1):
        if index in kept or not texts[index] or expected < "A":
            continue
        if texts[index] != expected:
            notes.append(f"read {texts[index]!r} where the sequence wants {expected!r}; corrected")
        kept.insert(0, index)
        letters.insert(0, expected)
        expected = chr(ord(expected) - 1)

    expected = chr(ord(letters[-1]) + 1)
    for index in range(max(kept) + 1, len(texts)):
        if index in kept or not texts[index] or expected > "Z":
            continue
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
    if letters[0] != "A":
        # Rehearsal letters begin at A.  A run that starts anywhere else is a
        # run of misreadings that happen to ascend, and placing it would put
        # the wrong letter over every bar it names — worse than placing none,
        # because a player trusts a letter.  Measured on a publisher's part
        # whose boxes are small and whose frames are broken: the longest
        # ascending run of what could be read was F to P, over marks that are
        # in fact A to O.
        return [], notes + [f"the letters read run from {letters[0]!r}, not from 'A'; "
                            f"none of them are used"], []
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
