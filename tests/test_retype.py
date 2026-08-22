"""Retyping: the wiring, the bar counting and the proofreading report.

The recognition itself is somebody else's program and is not tested here — what
is tested is that a page is counted, joined, checked and reported correctly, and
that the result tells the truth about how much of it to trust.
"""

import pytest

from sheeets import extract_part
from sheeets.retype import PageSpan, RetypeResult, count_bars_by_page
from sheeets.score_xml import MeasureCheck
from fractions import Fraction


def test_bars_are_counted_off_the_scan_before_anything_is_recognised(score_pdf):
    # The fixture draws 8 bars on every staff of every page.
    extraction = extract_part(score_pdf, part="bottom")
    counted = count_bars_by_page(extraction)
    assert sorted(counted) == [1, 2]
    assert all(count == 8 for count in counted.values()), counted


def result(**kwargs) -> RetypeResult:
    base = dict(
        part_name="Perc", engine="test", musicxml=None, fresh_pdf=None,
        draft_pdf=None, bars_in_scan=16, measures_read=16,
        checks=[MeasureCheck(n, Fraction(1), Fraction(1), 1) for n in range(1, 17)],
        spans=[PageSpan(3, 1, 8), PageSpan(4, 9, 16)],
        bars_by_page={3: 8, 4: 8},
    )
    base.update(kwargs)
    return RetypeResult(**base)


def test_a_clean_read_says_so():
    assert result().trustworthy
    assert "clean" in result().summary()


def test_a_measure_that_does_not_add_up_makes_it_untrustworthy():
    bad = [MeasureCheck(n, Fraction(1, 2) if n == 12 else Fraction(1), Fraction(1), 1)
           for n in range(1, 17)]
    out = result(checks=bad)
    assert not out.trustworthy
    assert [c.number for c in out.bad_measures] == [12]
    assert "needs proofreading" in out.summary()


def test_a_missing_bar_makes_it_untrustworthy_even_when_every_measure_adds_up():
    # The cross-check that no measure-level test can make: the engine simply
    # did not see four of the bars that are in the scan.
    assert not result(measures_read=12).trustworthy


def test_a_suspect_measure_is_traced_back_to_its_page():
    bad = [MeasureCheck(n, Fraction(1, 2) if n == 12 else Fraction(1), Fraction(1), 1)
           for n in range(1, 17)]
    out = result(checks=bad)
    assert out.page_of(12) == 4
    assert out.page_of(3) == 3
    assert out.page_of(999) is None
    report = out.report()
    assert report["suspect_measures"] == [
        {"measure": 12, "score_page": 4, "adds_up_to": "1/2", "should_be": "1"}
    ]
    assert report["pages"][1]["suspect"] == [12]
