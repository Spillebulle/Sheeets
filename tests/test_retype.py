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


def test_the_proof_sheet_shows_only_the_pages_worth_looking_at(score_pdf, tmp_path):
    import pymupdf

    from sheeets.proof import write_proof

    extraction = extract_part(score_pdf, part="bottom")
    bad = [MeasureCheck(n, Fraction(1, 2) if n == 12 else Fraction(1), Fraction(1), 1)
           for n in range(1, 17)]
    out = write_proof(extraction, result(checks=bad), tmp_path / "proof.pdf")
    with pymupdf.open(out) as document:
        text = "\n".join(page.get_text() for page in document)
    # Measure 12 is on score page 4, and page 3 was clean, so only 4 is printed.
    assert "score page 4" in text
    assert "score page 3" not in text
    assert "look at: 12" in text


def test_a_clean_proof_sheet_says_there_is_nothing_to_do(score_pdf, tmp_path):
    import pymupdf

    from sheeets.proof import write_proof

    extraction = extract_part(score_pdf, part="bottom")
    out = write_proof(extraction, result(), tmp_path / "proof.pdf")
    with pymupdf.open(out) as document:
        assert "nothing flagged" in document[0].get_text()


FAKE_ENGINE = '''
import pathlib, sys
inp, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
MEASURE = """    <measure number="%d">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type></note>
    </measure>
"""
for image in sorted(inp.glob("*.png")):
    body = "".join(MEASURE % n for n in range(1, 5))
    (out / (image.stem + ".musicxml")).write_text(
        \'<?xml version="1.0"?>\\n<score-partwise version="4.0">\'
        \'<part-list><score-part id="P1"><part-name>X</part-name></score-part></part-list>\'
        \'<part id="P1">\' + body + \'</part></score-partwise>\')
'''


@pytest.mark.skipif(
    not __import__("sheeets.engrave", fromlist=["x"]).LilyPondEngraver().available(),
    reason="LilyPond is not installed",
)
def test_the_whole_retype_runs_and_reports(score_pdf, tmp_path, monkeypatch):
    import pymupdf

    from sheeets.recognize import ExternalRecognizer
    from sheeets.retype import retype

    script = tmp_path / "engine.py"
    script.write_text(FAKE_ENGINE)
    monkeypatch.setenv("SHEEETS_OMR_COMMAND", f"python3 {script} {{input}} {{output}}")

    out = tmp_path / "fresh.pdf"
    result = retype(
        score_pdf, part="bottom", out=out, read_from="part",
        engine=ExternalRecognizer(), workdir=tmp_path / "work",
        proof=tmp_path / "proof.pdf", part_name="Perc", title="Fixture",
    )
    assert out.exists()
    assert result.musicxml.exists()
    assert result.proof_pdf.exists()
    with pymupdf.open(out) as document:
        assert document.page_count >= 1
    # Four measures per draft page, joined and renumbered from 1.
    assert result.measures_read == 4 * len(result.spans)
    assert result.spans[0].first_measure == 1
    # The fixture holds 8 bars per staff on each of its two pages; the fake
    # engine invents 4 per page, so the cross-check must call this suspect.
    assert result.bars_in_scan == 16
    assert not result.trustworthy
    assert result.report()["pages"]


def test_the_counts_are_made_to_add_up_to_what_the_page_says():
    """The printed bar numbers settle the total, so each rest is checked
    against arithmetic rather than against a second opinion from OCR."""
    from sheeets.retype import _fit_counts

    # Nothing to do.
    assert _fit_counts([7, 5], 12) == ([7, 5], "")

    # One unreadable: the sum names it.
    counts, note = _fit_counts([4, 16, None, 14, 34, 3], 95)
    assert counts == [4, 16, 24, 14, 34, 3] and "24" in note

    # One misread, and the correction looks like the misreading.
    counts, note = _fit_counts([44, 16], 20)
    assert counts == [4, 16] and "44" in note

    # Two unreadable, or a sum that no single change explains: refused.
    assert _fit_counts([None, None, 3], 30)[0] is None
    assert _fit_counts([7, 5], 40)[0] is None


def test_a_correction_has_to_look_like_the_misreading():
    from sheeets.retype import _plausible_misread

    assert _plausible_misread("44", "4")       # a digit doubled
    assert _plausible_misread("2", "27")       # a digit lost
    assert _plausible_misread("16", "18")      # one digit confused
    assert not _plausible_misread("3", "97")   # nothing in common
