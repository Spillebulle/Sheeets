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


def test_a_part_page_is_many_systems_of_one_staff_not_one_system():
    """The fleet's two part inputs were both read as one big system.

    On a part every gap between staves is the same size, so "a gap much bigger
    than the median" never fires.  What separates them is that nothing joins
    them: no barline bridges the gap.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    from sheeets.detect.projection import ProjectionDetector
    from sheeets.model import PageImage

    space = 11
    for joined in (True, False):
        image = Image.new("L", (1400, 700), 255)
        draw = ImageDraw.Draw(image)
        tops = [100, 300, 500]
        if joined:
            draw.line([(150, tops[0]), (150, tops[-1] + 4 * space)], fill=0, width=4)
        for y in tops:
            for k in range(5):
                draw.line([(150, y + k * space), (1300, y + k * space)], fill=0, width=2)
            for x in (150, 700, 1300):
                draw.line([(x, y), (x, y + 4 * space)], fill=0, width=3)
        page = ProjectionDetector().detect(
            PageImage(index=0, array=np.asarray(image), dpi=300)
        )
        counts = [len(s) for s in page.systems]
        assert counts == ([3] if joined else [1, 1, 1]), (joined, counts)
