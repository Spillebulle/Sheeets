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


def test_a_barline_is_what_crosses_the_system_not_one_staff():
    """A stem crosses its own staff; a barline crosses the others too."""
    import numpy as np
    from PIL import Image, ImageDraw

    from sheeets.detect.projection import ProjectionDetector
    from sheeets.model import PageImage
    from sheeets.reflow import system_barlines

    space = 11
    image = Image.new("L", (1600, 620), 255)
    draw = ImageDraw.Draw(image)
    tops = [80, 260, 440]
    draw.line([(150, tops[0]), (150, tops[-1] + 4 * space)], fill=0, width=4)
    for y in tops:
        for k in range(5):
            draw.line([(150, y + k * space), (1500, y + k * space)], fill=0, width=2)
        for x in (150, 600, 1050, 1500):          # real barlines, on every staff
            draw.line([(x, y), (x, y + 4 * space)], fill=0, width=3)
    # A long stem crossing only the middle staff, where no barline is.
    draw.line([(820, tops[1]), (820, tops[1] + 4 * space)], fill=0, width=3)

    page = ProjectionDetector().detect(PageImage(index=0, array=np.asarray(image), dpi=300))
    system = page.systems[0]
    assert len(system.staves) == 3
    found = system_barlines(page, system)
    assert len(found) == 4, found
    assert all(min(abs(f - x) for x in (150, 600, 1050, 1500)) <= 4 for f in found)


def test_a_zero_width_piece_is_dropped_not_exported():
    """A staff detected at the very edge of a bad scan produced an empty
    band, and the PDF exporter died on it with "cannot write empty image"."""
    import numpy as np

    from sheeets.model import Band
    from sheeets.reflow import segments_for_band

    band = Band(page_index=0, system_index=0, staff_index=0, x0=0, y0=0,
                x1=0, y1=10, space=11.0, music_x0=0)
    empty = np.full((10, 0), 255, np.uint8)
    assert segments_for_band(empty, band, 0, 5, max_source_width=100, dpi=300) == []


def test_a_one_staff_system_still_has_barlines():
    """A part is one staff per system, and its bars still have to be counted.

    Cross-staff support asks two staves to agree, which is what tells a barline
    from a note stem in a score.  A part has no second staff to ask, and the
    rule as written demanded two votes however many staves there were — so
    every publisher's part counted zero bars in the scan and the retype had
    nothing to check the recognition against.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    from sheeets.detect.projection import ProjectionDetector
    from sheeets.model import PageImage
    from sheeets.reflow import system_barlines

    space = 16
    image = Image.new("L", (1600, 300), 255)
    draw = ImageDraw.Draw(image)
    top = 120
    for k in range(5):
        draw.line([(150, top + k * space), (1500, top + k * space)], fill=0, width=2)
    for x in (150, 600, 1050, 1500):
        draw.line([(x, top), (x, top + 4 * space)], fill=0, width=3)
    # A stem: it hangs off a notehead, so it reaches one outer line, not both.
    draw.line([(820, top), (820, top + 3 * space)], fill=0, width=3)

    page = ProjectionDetector().detect(PageImage(index=0, array=np.asarray(image), dpi=300))
    system = page.systems[0]
    assert len(system.staves) == 1
    found = system_barlines(page, system)
    assert len(found) == 4, found


def test_a_cut_does_not_slice_what_is_written_over_the_barline():
    """A rehearsal box sits centred on a barline, so cutting the system there
    puts half of it at the end of one line and half at the start of the next."""
    import numpy as np

    from sheeets.reflow import _clear_of_markings

    space = 16.0
    top, bottom = 100, 100 + int(4 * space)
    image = np.full((bottom + 120, 1000), 255, dtype=np.uint8)
    # A box above the staff, straddling the barline at x = 500.
    image[int(top - 3 * space) : int(top - 0.5 * space), 480:520] = 0

    moved = _clear_of_markings([(0, 500), (500, 1000)], image, top, bottom, space)
    assert moved[0][1] <= 480, moved           # the whole box goes to the next piece
    assert moved[1][0] == moved[0][1]

    # Nothing above the barline: the cut stays where the music put it.
    clean = np.full((bottom + 120, 1000), 255, dtype=np.uint8)
    assert _clear_of_markings([(0, 500), (500, 1000)], clean, top, bottom, space) == \
        [(0, 500), (500, 1000)]


def test_a_stem_on_a_lone_staff_is_not_a_barline():
    """A part is one staff to a system, so there is nothing to vote with — and
    a stem from the top line to the bottom passes the full-height test.  On a
    real drum-kit part that made 518 barlines out of about seventy bars."""
    import numpy as np
    from PIL import Image, ImageDraw

    from sheeets.detect.projection import ProjectionDetector
    from sheeets.model import PageImage
    from sheeets.reflow import system_barlines

    space = 16
    image = Image.new("L", (1600, 300), 255)
    draw = ImageDraw.Draw(image)
    top = 120
    for k in range(5):
        draw.line([(150, top + k * space), (1500, top + k * space)], fill=0, width=2)
    for x in (150, 600, 1050, 1500):
        draw.line([(x, top), (x, top + 4 * space)], fill=0, width=3)
    # A stem the full height of the staff, with its notehead beside it.
    draw.line([(820, top), (820, top + 4 * space)], fill=0, width=3)
    draw.ellipse([823, top + 4 * space - 8, 823 + 20, top + 4 * space + 4], fill=0)

    page = ProjectionDetector().detect(PageImage(index=0, array=np.asarray(image), dpi=300))
    system = page.systems[0]
    assert len(system.staves) == 1
    found = system_barlines(page, system)
    assert len(found) == 4, found
    assert all(abs(f - 820) > 20 for f in found)
