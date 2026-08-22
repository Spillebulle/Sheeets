import numpy as np
import pytest

from sheeets.detect.projection import ProjectionDetector, horizontal_runs, otsu
from sheeets.model import PageImage
from tests.conftest import SPACE, STAVES


def detect(image, **kwargs):
    array = np.asarray(image)
    page = PageImage(index=0, array=array, dpi=300.0, label="p1")
    return ProjectionDetector(**kwargs).detect(page)


def test_horizontal_runs_keeps_only_long_runs():
    mask = np.zeros((3, 20), dtype=bool)
    mask[0, 2:14] = True   # long
    mask[1, 5:8] = True    # short
    mask[2, 0:6] = True    # exactly at the limit
    kept = horizontal_runs(mask, 6)
    assert kept[0].sum() == 12
    assert kept[1].sum() == 0
    assert kept[2].sum() == 6


def test_otsu_splits_a_two_tone_image():
    arr = np.concatenate([np.full(500, 20, np.uint8), np.full(500, 230, np.uint8)])
    assert 20 < otsu(arr.reshape(1, -1)) < 230


def test_finds_every_staff(page_image, expected_tops):
    result = detect(page_image)
    assert len(result.staves) == STAVES
    assert result.space == pytest.approx(SPACE, rel=0.1)
    found = sorted(s.top for s in result.staves)
    for got, want in zip(found, expected_tops):
        assert abs(got - want) < SPACE


def test_deskews_a_tilted_page_and_still_finds_them(page_image):
    from make_fixture import draw_page

    tilted = draw_page(staves=STAVES, space=SPACE, skew_deg=0.45)
    result = detect(tilted)
    assert len(result.staves) == STAVES
    # The correction is reported, and it points the right way: with the sign
    # backwards the skew doubles instead of cancelling, which is how the bug
    # showed up on the score this was written against.
    assert abs(result.skew_deg) == pytest.approx(0.45, abs=0.1)
    residual = ProjectionDetector(deskew=False).detect(
        PageImage(index=0, array=result.image, dpi=300.0)
    )
    assert len(residual.staves) == STAVES


def test_reports_why_a_blank_page_found_nothing():
    blank = np.full((400, 800), 255, np.uint8)
    result = detect(blank)
    assert result.systems == []
    assert "reason" in result.notes


def test_a_line_broken_into_fragments_is_still_a_line():
    """Where print has faded, one staff line comes back as several pieces.

    Filtering pieces by width before putting them back together threw away two
    whole systems of the crooked part in the fleet.
    """
    from PIL import Image, ImageDraw

    space = 11
    image = Image.new("L", (2000, 400), 255)
    draw = ImageDraw.Draw(image)
    top = 150
    for k in range(5):
        y = top + k * space
        if k in (1, 3):
            # a faded line: drawn in pieces, none of them wide on its own
            for x0 in range(150, 1850, 260):
                draw.line([(x0, y), (x0 + 170, y)], fill=0, width=2)
        else:
            draw.line([(150, y), (1850, y)], fill=0, width=2)
    result = detect(image)
    assert len(result.staves) == 1
    assert abs(result.staves[0].top - top) <= 2


def test_a_staff_is_recovered_where_the_grid_says_one_belongs():
    """A gap of exactly two staves' spacing is a staff that was not found."""
    from sheeets.detect.projection import recover_gaps

    space = 11.0
    groups = [[100 + k * space for k in range(5)],
              [300 + k * space for k in range(5)],
              # the staff at 500 is missing
              [700 + k * space for k in range(5)],
              [900 + k * space for k in range(5)]]
    ys = [y for g in groups for y in g] + [500.0, 522.0, 544.0]  # three lines survive
    recovered = recover_gaps(groups, ys, space)
    assert len(recovered) == 5
    assert any(abs(g[0] - 500) < 2 for g in recovered)


def test_nothing_is_invented_where_the_grid_is_even():
    from sheeets.detect.projection import recover_gaps

    space = 11.0
    groups = [[100 + i * 200 + k * space for k in range(5)] for i in range(4)]
    ys = [y for g in groups for y in g]
    assert len(recover_gaps(groups, ys, space)) == 4
