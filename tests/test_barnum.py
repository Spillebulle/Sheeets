"""Bar numbers and multi-measure rests: the two things a part prints about
itself, and the only outside check on how many bars were recognised."""

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from sheeets.barnum import (
    BarNumber, Candidate, SystemFacts, bars_wanted, choose, multi_rests,
    with_first_bar,
)

SPACE = 18.0


def _italic(size):
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                 "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class _Staff:
    def __init__(self, top, space=SPACE, x0=150):
        self.lines = [top + k * space for k in range(5)]
        self.space = space
        self.x0 = x0
        self.x1 = 2200

    @property
    def top(self):
        return self.lines[0]

    @property
    def bottom(self):
        return self.lines[-1]


def page_with_rests(counts=(4, 16), width=2400, height=400, top=200):
    """A staff with multi-measure rests drawn the way an engraving draws them:
    a thick bar centred on the middle line, with the count in bold above."""
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    staff = _Staff(top)
    for y in staff.lines:
        draw.line([(staff.x0, y), (staff.x1, y)], fill=0, width=2)
    middle = staff.lines[2]
    font = _italic(int(SPACE * 1.9))
    for n, count in enumerate(counts):
        x = 400 + n * 700
        draw.rectangle([x, middle - 0.3 * SPACE, x + 200, middle + 0.3 * SPACE], fill=0)
        draw.line([(x, middle - 1.4 * SPACE), (x, middle + 1.4 * SPACE)], fill=0, width=4)
        draw.line([(x + 200, middle - 1.4 * SPACE), (x + 200, middle + 1.4 * SPACE)],
                  fill=0, width=4)
        label = str(count)
        box = draw.textbbox((0, 0), label, font=font)
        draw.text((x + 100 - (box[2] - box[0]) // 2, top - 3.4 * SPACE),
                  label, fill=0, font=font)
    return np.asarray(image), staff


def test_the_thick_bar_is_found_and_a_barline_is_not():
    image, staff = page_with_rests((4, 16))
    found = multi_rests(image, staff)
    assert len(found) == 2, [(r.x0, r.x1) for r in found]
    assert abs(found[0].x0 - 400) <= 6 and abs(found[1].x0 - 1100) <= 6


@pytest.mark.skipif(
    not __import__("shutil").which("tesseract"), reason="tesseract not installed"
)
def test_the_count_over_the_bar_is_read():
    image, staff = page_with_rests((4, 16))
    assert [r.count for r in multi_rests(image, staff)] == [4, 16]


def test_the_numbers_are_chosen_so_the_run_ascends():
    """Each system offers several digit clusters; only one of them can be the
    bar number, and which one is settled by the sequence, not by the reading."""
    per_system = [
        (0, 0, [Candidate(9, 170, 10), Candidate(3, 900, 10)]),
        (0, 1, [Candidate(88, 400, 10), Candidate(27, 168, 10)]),
        (0, 2, [Candidate(41, 166, 10)]),
        (0, 3, []),
        (0, 4, [Candidate(2, 500, 10)]),
        (0, 5, [Candidate(59, 170, 10)]),
    ]
    chosen, notes = choose(per_system)
    assert [c.value for c in chosen] == [9, 27, 41, 59]
    assert any("500" not in n for n in notes)


def test_the_first_system_is_bar_one():
    chosen = [BarNumber(0, 1, 9), BarNumber(0, 2, 27)]
    assert [b.value for b in with_first_bar(chosen, 0, 0)] == [1, 9, 27]


def test_a_span_needs_two_numbers_in_a_row():
    facts = [
        SystemFacts(0, 0, number=1),
        SystemFacts(0, 1, number=9),
        SystemFacts(0, 2, number=None),
        SystemFacts(0, 3, number=41),
    ]
    wanted = bars_wanted(facts)
    assert wanted == {(0, 0): 8}       # 1 -> 9 only; the gap is not attributed
