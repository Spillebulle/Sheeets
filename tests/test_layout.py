from sheeets.layout import group_systems
from sheeets.model import Staff


def staff(top: float, space: float = 11.0) -> Staff:
    return Staff(lines=[top + k * space for k in range(5)], space=space, x0=100, x1=900)


def test_one_system_when_the_gaps_are_even():
    staves = [staff(100 + i * 120) for i in range(6)]
    systems = group_systems(staves, 11.0, page_index=0)
    assert len(systems) == 1
    assert [s.index for s in systems[0].staves] == [0, 1, 2, 3, 4, 5]


def test_splits_where_the_gap_is_much_bigger():
    staves = [staff(100), staff(220), staff(340), staff(900), staff(1020)]
    systems = group_systems(staves, 11.0, page_index=0)
    assert [len(s) for s in systems] == [3, 2]
    assert [s.index for s in systems[1].staves] == [0, 1]


def test_family_gaps_in_a_score_do_not_start_a_new_system():
    # A brass band score leaves a little more room between families; at 1.2x the
    # normal gap that must not read as a system break.
    tops, y = [], 100.0
    for i in range(12):
        tops.append(y)
        y += 120 if i % 4 else 145
    systems = group_systems([staff(t) for t in tops], 11.0, page_index=0)
    assert len(systems) == 1
