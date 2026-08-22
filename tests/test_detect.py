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
