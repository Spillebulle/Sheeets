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


def test_a_barline_anywhere_joins_a_system_not_just_at_the_left_edge():
    """Looking only at the left edge depends on knowing where the staff starts.

    When one staff line is detected a little short, that window misses the
    barline and a nineteen-stave system splits in two.  Every barline in a
    system joins its staves, so any of them will do.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    from sheeets.detect.projection import ProjectionDetector
    from sheeets.model import PageImage

    space = 11
    image = Image.new("L", (1400, 700), 255)
    draw = ImageDraw.Draw(image)
    tops = [100, 300]
    for y in tops:
        for k in range(5):
            draw.line([(150, y + k * space), (1300, y + k * space)], fill=0, width=2)
    # No bracket at the left; the staves are joined by a barline in the middle.
    draw.line([(700, tops[0]), (700, tops[1] + 4 * space)], fill=0, width=3)
    page = ProjectionDetector().detect(PageImage(index=0, array=np.asarray(image), dpi=300))
    assert [len(s) for s in page.systems] == [2]


def test_a_score_that_breaks_its_barlines_between_families_is_still_one_system():
    """This score breaks the barline between the basses and the percussion.

    On two of its 27 pages nothing bridges that gap, and the ink alone split a
    19-stave system into 14 and 5. Systems on a page carry the same
    instruments, so groups of different sizes mean the split is wrong.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    from sheeets.detect.projection import ProjectionDetector
    from sheeets.model import PageImage

    space = 11
    image = Image.new("L", (1400, 900), 255)
    draw = ImageDraw.Draw(image)
    tops = [100, 250, 400, 600, 750]        # a wider gap before the last two
    for y in tops:
        for k in range(5):
            draw.line([(150, y + k * space), (1300, y + k * space)], fill=0, width=2)
    # Barlines join staves 1-3 and, separately, staves 4-5: a family break.
    for x in (150, 700, 1300):
        draw.line([(x, tops[0]), (x, tops[2] + 4 * space)], fill=0, width=3)
        draw.line([(x, tops[3]), (x, tops[4] + 4 * space)], fill=0, width=3)
    page = ProjectionDetector().detect(PageImage(index=0, array=np.asarray(image), dpi=300))
    # 3 and 2 are not equal, so the break is a broken barline, not a boundary.
    assert [len(s) for s in page.systems] == [5]


def test_even_groups_are_believed():
    from sheeets.layout import _groups_are_even

    assert _groups_are_even([False, True, False, True, False])   # 2,2,2
    assert _groups_are_even([True, True, True])                  # 1,1,1,1
    assert not _groups_are_even([False, False, True, False])     # 3,2


def test_uneven_groups_are_regularised_when_the_sizes_say_how():
    """One page of the three-player set came back [3, 1, 1, 1, 3, 3, 3].

    Its second system's inner barlines were too faint to find. The three
    singletons plainly make up the missing three, and merging them is safe.
    """
    from sheeets.layout import _regularise, _sizes

    breaks = [False, False, True, True, True, True, False, False, True,
              False, False, True, False, False]
    assert _sizes(breaks) == [3, 1, 1, 1, 3, 3, 3]
    repaired = _regularise(breaks)
    assert repaired is not None
    assert _sizes(repaired) == [3, 3, 3, 3, 3]


def test_groups_that_cannot_be_made_even_are_left_alone():
    from sheeets.layout import _regularise

    # 14 and 5: no merging makes these equal, and guessing would be worse.
    assert _regularise([False] * 13 + [True] + [False] * 4) is None
    # A group larger than the modal size is not something to take apart.
    assert _regularise([False, True, False, False, False, True, False]) is None
