"""Rehearsal marks: found by their box, read one character at a time."""

import shutil

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from sheeets.marks import Mark, find_boxes, find_marks, measure_of

SPACE = 11.0


def _serif(size):
    """A real typeface, at a size that fills the box the way an engraving does.

    The default PIL bitmap font draws a letter six pixels wide inside a box of
    sixty, which no engraver has ever done, and a reader written against that
    fixture is not written against rehearsal marks.
    """
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                 "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def page_with_box(letter="A", side=50, at=(400, 100), extra_noise=True):
    image = Image.new("L", (2000, 400), 255)
    draw = ImageDraw.Draw(image)
    x, y = at
    draw.rectangle([x, y, x + side, y + side], outline=0, width=3)
    if letter.strip():
        font = _serif(int(side * 0.62))
        box = draw.textbbox((0, 0), letter, font=font)
        draw.text((x + (side - (box[2] - box[0])) // 2 - box[0],
                   y + (side - (box[3] - box[1])) // 2 - box[1]),
                  letter, fill=0, font=font)
    if extra_noise:
        # A slur and a dynamic in the same band must not be mistaken for a box.
        draw.arc([700, 110, 900, 170], start=200, end=340, fill=0, width=3)
        draw.text((1200, 120), "ff", fill=0)
    top_row = 200
    for k in range(5):
        draw.line([(100, top_row + k * SPACE), (1900, top_row + k * SPACE)], fill=0, width=2)
    return np.asarray(image), top_row


def test_the_box_is_found_and_nothing_else_is():
    image, top = page_with_box()
    boxes = find_boxes(image, top, SPACE)
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert abs(x - 400) <= 3 and abs(y - 100) <= 3
    assert 45 <= w <= 56 and 45 <= h <= 56


def test_a_box_below_the_staff_is_not_a_rehearsal_mark():
    image, top = page_with_box(at=(400, 300))  # under the staff, not over it
    assert find_boxes(image, top, SPACE) == []


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_the_letter_inside_is_read():
    image, top = page_with_box("A", side=60, at=(400, 95))
    assert [m.text for m in find_marks(image, top, SPACE)] == ["A"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_an_empty_box_is_not_a_rehearsal_mark():
    # The shape test is generous on purpose; OCR is what rejects the leftovers.
    image, top = page_with_box(" ", side=60, at=(400, 95))
    assert find_boxes(image, top, SPACE)  # the shape is there
    assert find_marks(image, top, SPACE) == []  # but nothing readable is in it


def test_a_mark_belongs_to_the_bar_it_sits_over():
    barlines = [100, 500, 900, 1300]
    assert measure_of(Mark("A", 480, 0, 40, 40), barlines) == 1  # over the 2nd barline
    assert measure_of(Mark("B", 950, 0, 40, 40), barlines) == 2
    assert measure_of(Mark("C", 50, 0, 40, 40), barlines) == 0
    assert measure_of(Mark("D", 50, 0, 40, 40), []) == 0


def test_the_sequence_repairs_a_misread_letter():
    from sheeets.marks import tidy_sequence

    # C read as G and O read as zero — both happened on the real score.
    got, notes, kept = tidy_sequence(["A", "B", "G", "D", "E", "F", "G", "H"])
    assert got == list("ABCDEFGH")
    assert len(kept) == 8
    assert any("wants 'C'" in note for note in notes)


def test_strays_anywhere_in_the_run_are_dropped():
    """Exactly what the box detector returned on the real score, junk and all."""
    from sheeets.marks import tidy_sequence

    reads = ["B", "L", "H", "A", "B", "C", "D", "E", "F", "K",
             "G", "H", "I", "J", "K", "L", "I", "M", "N", "O"]
    got, notes, kept = tidy_sequence(reads)
    assert "".join(got) == "ABCDEFGHIJKLMNO"
    assert len(kept) == 15
    assert sum(1 for n in notes if "dropped" in n) == 5


def test_a_chain_that_starts_late_is_extended_backwards():
    """"A B" scores two against a clean "D..N" of eleven, so the exact chain
    starts late and the first marks have to be reached back into."""
    from sheeets.marks import tidy_sequence

    reads = ["Y", "A", "B", "G", "D", "E", "F", "G", "H",
             "I", "J", "K", "L", "M", "N", "0"]
    got, notes, kept = tidy_sequence(reads)
    assert "".join(got) == "ABCDEFGHIJKLMNO"
    assert len(kept) == 15  # the stray "Y" is gone


def test_too_few_to_judge_are_left_alone():
    from sheeets.marks import tidy_sequence

    got, notes, kept = tidy_sequence(["A", "B"])
    assert got == ["A", "B"] and notes == []


def test_what_is_not_a_run_of_letters_is_not_used():
    """Wrong marks are worse than no marks: a player trusts a letter."""
    from sheeets.marks import tidy_sequence

    # Marks numbered rather than lettered.
    got, notes, kept = tidy_sequence(["1", "2", "3", "4"])
    assert got == [] and kept == [] and notes

    # A run that ascends but does not begin at A is a run of misreadings.
    got, notes, kept = tidy_sequence(["O", "H", "F", "G", "H", "I", "J", "K"])
    assert got == [] and kept == [] and notes
