import numpy as np
import pytest

from sheeets.paper import PageSetup
from sheeets.reflow import barlines, cut_points, scale_for


def band_with_barlines(cols, width=1000, height=60, top=10, bottom=50):
    band = np.full((height, width), 255, np.uint8)
    for k in range(5):
        band[top + k * 10, :] = 0
    for x in cols:
        band[top : bottom + 1, x : x + 3] = 0
    return band


def test_finds_the_barlines_and_not_the_stems():
    band = band_with_barlines([100, 400, 700])
    # A stem is tall but does not reach both outer lines.
    band[20:48, 550:552] = 0
    found = barlines(band, 10, 50)
    assert [abs(f - want) <= 3 for f, want in zip(found, [101, 401, 701])] == [True] * 3
    assert len(found) == 3


def test_pieces_are_even_and_land_on_barlines():
    cols = list(range(100, 3100, 100))
    pieces = cut_points(3000, 1100, cols)
    assert len(pieces) == 3
    widths = [b - a for a, b in pieces]
    assert max(widths) <= 1100
    assert max(widths) - min(widths) <= 200  # even, not greedy-with-a-stub
    assert all(b in cols for _, b in pieces[:-1])


def test_a_narrow_system_is_left_alone():
    assert cut_points(800, 1000, [100, 200]) == [(0, 800)]


def test_a_bar_wider_than_the_page_is_cut_anyway():
    pieces = cut_points(3000, 1000, [1500])
    assert all(b - a <= 1000 for a, b in pieces)
    # The one barline there is gets used even though it leaves a short line:
    # a short line is a cosmetic problem, a sliced bar is a musical one.
    assert 1500 in [b for _, b in pieces[:-1]]


def test_a_cut_never_lands_mid_bar_when_a_barline_is_in_reach():
    # Bars far wider than the snap window: the aim lands between barlines every
    # time, and the fallback has to pull it back onto one.  This is the defect
    # that put a cut through the middle of bar 4 of the first real part.
    cols = [400, 900, 1400, 1900, 2400, 2900]
    pieces = cut_points(3200, 1000, cols)
    assert all(b - a <= 1000 for a, b in pieces)
    assert all(b in cols for _, b in pieces[:-1])


def test_a_faint_barline_is_still_a_barline():
    # Real print: 93 % coverage and the top pixel a row short of the fitted
    # line.  Testing the exact outer row at 95 % rejected three in a row.
    band = band_with_barlines([500])
    band[10:12, 500:503] = 255  # rub out the top of it
    assert barlines(band, 10, 50)


def test_scale_targets_a_real_staff_size():
    # 11 px at 300 dpi is 0.93 mm; a part wants about 1.75 mm.
    assert scale_for(11, 300, 1.75) == pytest.approx(1.88, abs=0.02)
    assert scale_for(0, 300, 1.75) == 1.0


def test_page_setup_knows_how_much_source_fits():
    setup = PageSetup(size="a4", margin_mm=14, staff_mm=1.75)
    limit = setup.source_width_limit_px(11.0, 300.0)
    # 182 mm of paper at 1.88x is about 97 mm of source, which is 1143 px.
    assert 1050 < limit < 1250
    assert PageSetup(landscape=True).usable_width_mm > PageSetup().usable_width_mm
