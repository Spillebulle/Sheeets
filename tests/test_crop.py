"""The band around a staff: keep the markings, leave the page furniture."""

import numpy as np
from PIL import Image, ImageDraw

from sheeets.crop import band_for, longest_run
from sheeets.detect.projection import ProjectionDetector
from sheeets.model import PageImage

SPACE = 11


def page_with(marks) -> PageImage:
    """Two staves, plus whatever `marks` draws under the lower one."""
    image = Image.new("L", (2000, 700), 255)
    draw = ImageDraw.Draw(image)
    for staff, y_top in enumerate((150, 400)):
        for k in range(5):
            draw.line([(200, y_top + k * SPACE), (1900, y_top + k * SPACE)], fill=0, width=2)
        for b in range(5):
            x = 200 + 1700 * b / 4
            draw.line([(x, y_top), (x, y_top + 4 * SPACE)], fill=0, width=3)
    marks(draw, 400 + 4 * SPACE)
    return PageImage(index=0, array=np.asarray(image), dpi=300.0)


def bottom_band(marks):
    """Returns (band, staff bottom) for the lower of the two staves."""
    page = ProjectionDetector().detect(page_with(marks))
    system = page.systems[0]
    return band_for(page, system, [len(system.staves) - 1]), system.staves[-1].bottom


def band_below(marks) -> float:
    band, bottom = bottom_band(marks)
    return (band.y1 - bottom) / SPACE


def test_a_marking_under_the_staff_is_kept():
    ink_at = None

    def marks(draw, y):
        nonlocal ink_at
        ink_at = y + 4 * SPACE
        draw.text((500, ink_at), "mf + B.Dr.", fill=0)

    band, _ = bottom_band(marks)
    assert band.y1 > ink_at + 6  # the whole marking, not its first few rows


def test_a_line_of_text_across_the_page_is_not():
    ink_at = None

    def marks(draw, y):
        nonlocal ink_at
        ink_at = int(y + 5 * SPACE)
        # A copyright line: one long unbroken stretch of ink.
        draw.line([(600, ink_at), (1400, ink_at)], fill=0, width=6)

    band, _ = bottom_band(marks)
    assert band.y1 < ink_at


def test_nothing_under_the_staff_still_leaves_air():
    assert 1.0 < band_below(lambda draw, y: None) < 3.0


def test_longest_run_lets_small_gaps_through():
    row = np.zeros(400, bool)
    row[10:30] = True
    row[35:60] = True   # 5 px gap: same stretch
    row[200:210] = True  # far away: its own stretch
    assert longest_run(row, gap=12) == 50  # 10..59 inclusive
    assert longest_run(np.zeros(10, bool)) == 0


def test_growth_stops_at_the_midpoint_between_two_staves():
    page = ProjectionDetector().detect(page_with(lambda draw, y: None))
    system = page.systems[0]
    band = band_for(page, system, [1])
    # The upper staff ends at 150 + 4*SPACE; the band must not reach past
    # halfway to it, whatever the padding asks for.
    midpoint = (system.staves[0].bottom + system.staves[1].top) / 2
    assert band.y0 >= midpoint - 1
