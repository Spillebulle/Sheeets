import pytest

from sheeets.model import Staff, System
from sheeets.select import AllSelector, IndexSelector, RangeSelector, parse


def system(n: int) -> System:
    staves = [
        Staff(lines=[100 + i * 120 + k * 11 for k in range(5)], space=11, x0=0, x1=100, index=i)
        for i in range(n)
    ]
    return System(staves=staves, page_index=0)


def test_bottom_and_top():
    s = system(19)
    assert parse("bottom").select(s) == [18]
    assert parse("top").select(s) == [0]
    assert parse("-2").select(s) == [17]
    assert parse("3").select(s) == [3]


def test_range_covers_a_two_staff_part():
    assert parse("17..18").select(system(19)) == [17, 18]
    assert RangeSelector(-2, -1).select(system(19)) == [17, 18]


def test_all_is_how_an_already_extracted_part_passes_through():
    assert AllSelector().select(system(1)) == [0]
    assert parse("all").select(system(3)) == [0, 1, 2]


def test_out_of_range_selects_nothing_rather_than_the_wrong_staff():
    assert IndexSelector(25).select(system(19)) == []
    assert IndexSelector(-25).select(system(19)) == []


def test_unreadable_spec_says_what_is_allowed():
    with pytest.raises(ValueError, match="bottom"):
        parse("the drum one")


class _FakeOcr:
    """Labels as they actually come off a 300 dpi score, brackets and all."""

    READS = ["' Solo Cornet I", ". Flugel [", "'. Ist Horn I", "= Euphonium l",
             ". Timpani [", ". Optional* Percussion"]

    def __init__(self):
        self.calls = 0

    def image_to_string(self, picture, config=""):  # pragma: no cover - not used
        raise AssertionError("read_labels is patched in these tests")


def _labels(monkeypatch, reads=None):
    import sheeets.ocr as ocr_module

    seen = {"calls": 0}

    def fake(system, image=None, ocr=None):
        seen["calls"] += 1
        return list(reads if reads is not None else _FakeOcr.READS)

    monkeypatch.setattr(ocr_module, "read_labels", fake)
    return seen


def test_a_name_is_matched_through_the_ocr_that_read_it(monkeypatch):
    """Read off a real score the names come back with the staff's bracket and
    a stray tick in them; asking for an exact substring is asking OCR to be
    perfect for no reason."""
    _labels(monkeypatch)
    s = system(6)
    assert parse("name:Timpani").select(s) == [4]
    assert parse("name:Percussion").select(s) == [5]
    assert parse("name:Euphonium").select(s) == [3]
    assert parse("name:1st Horn").select(s) == [2]     # printed, and read, "Ist"


def test_a_name_that_is_not_there_selects_nothing(monkeypatch):
    _labels(monkeypatch)
    assert parse("name:Bassoon").select(system(6)) == []


def test_the_staff_is_remembered_so_later_pages_need_no_reading(monkeypatch):
    """Many scores print the names on the first page only — and reading them
    again on every page of a 27-page score is five hundred OCR calls."""
    seen = _labels(monkeypatch)
    selector = parse("name:Timpani")
    s = system(6)
    assert selector.select(s) == [4]
    blank = _labels(monkeypatch, reads=[""] * 6)
    assert selector.select(s) == [4]
    assert blank["calls"] == 0


def test_likeness_is_on_letters_alone():
    from sheeets.select import _likeness

    assert _likeness("Timpani", ". Timpani [") == 1.0
    assert _likeness("Eb Bass", "_y Eb Bass -~") == 1.0
    assert _likeness("Percussion", ". Optional* Percussion") == 1.0
    assert _likeness("Trombone", "Euphonium l") < 0.8
