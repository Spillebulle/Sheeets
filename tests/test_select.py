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
