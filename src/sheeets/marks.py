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
    border_ink: float = 0.45,
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
    """OCR the inside of one box: a single letter or number."""
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


def tidy_sequence(texts: list[str]) -> tuple[list[str], list[str]]:
    """Repair misreads, and drop strays, using the one thing marks guarantee.

    Rehearsal letters run in order.  That is a stronger fact than any single
    OCR result at this size, where the classic confusions all bite: C read as
    G, O read as zero, I as one, S as five.  Both of the first two happened on
    this score, and a stray box on the title page read as "Y" and sat in front
    of the run.

    So the longest ascending run wins: every position it covers is corrected to
    the letter that position demands, and anything before it that does not fit
    is dropped as a shape that was never a rehearsal mark.  If no run can be
    found — a score numbering its marks 1, 2, 3, or one that genuinely skips
    letters — nothing is touched, because then the sequence is not evidence.

    Returns the letters (strays removed) and a note of every change.
    """
    if len(texts) < 3:
        return list(texts), []

    best = None  # (matches, start index)
    for start in range(len(texts)):
        letter = texts[start]
        if len(letter) != 1 or not letter.isalpha():
            continue
        last = chr(ord(letter) + len(texts) - start - 1)
        if last > "Z":
            continue
        matches = sum(
            1 for i in range(start, len(texts))
            if texts[i] == chr(ord(letter) + i - start)
        )
        if best is None or matches > best[0]:
            best = (matches, start)

    if best is None:
        return list(texts), []
    matches, start = best
    covered = len(texts) - start
    if matches < max(3, 0.6 * covered):
        return list(texts), []

    anchor = ord(texts[start])
    kept: list[str] = []
    notes: list[str] = []
    for index in range(start):
        notes.append(f"dropped {texts[index]!r}: it is not part of the run")
    for index in range(start, len(texts)):
        want = chr(anchor + index - start)
        if texts[index] != want:
            notes.append(f"read {texts[index]!r} where the sequence wants {want!r}; corrected")
        kept.append(want)
    return kept, notes


def measure_of(mark: Mark, barlines: list[int]) -> int:
    """Which bar of the system a mark belongs to, counting from 0.

    A rehearsal mark sits over the barline that begins its bar, so the bar it
    marks is the one starting at or just before it.
    """
    if not barlines:
        return 0
    before = [i for i, x in enumerate(barlines) if x <= mark.centre_x + 4]
    return max(0, (before[-1] if before else 0))
