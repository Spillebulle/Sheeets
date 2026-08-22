"""Joining and checking MusicXML — the part of retyping that needs no engine."""

from fractions import Fraction
from xml.etree import ElementTree as ET

import pytest

from sheeets import score_xml

SCORE = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      {notes}
    </measure>
  </part>
</score-partwise>
"""
FULL_BAR = "<note><duration>8</duration><type>whole</type></note>"
HALF_BAR = "<note><duration>4</duration><type>half</type></note>"


def make(tmp_path, name, notes=FULL_BAR):
    path = tmp_path / name
    path.write_text(SCORE.format(notes=notes))
    return path


def test_pages_are_joined_and_renumbered(tmp_path):
    files = [make(tmp_path, f"p{i}.musicxml") for i in range(3)]
    tree = score_xml.merge(files)
    numbers = [m.get("number") for m in tree.getroot().find("part").findall("measure")]
    assert numbers == ["1", "2", "3"]


def test_a_measure_that_does_not_add_up_is_reported(tmp_path):
    tree = score_xml.merge([make(tmp_path, "a.musicxml", HALF_BAR)])
    check = score_xml.check(tree)[0]
    assert not check.ok
    assert check.beats == Fraction(1, 2)
    assert check.expected == Fraction(1)


def test_a_measure_that_adds_up_passes(tmp_path):
    tree = score_xml.merge([make(tmp_path, "a.musicxml")])
    assert all(c.ok for c in score_xml.check(tree))


def test_a_chord_is_not_counted_twice(tmp_path):
    notes = FULL_BAR + '<note><chord/><duration>8</duration><type>whole</type></note>'
    tree = score_xml.merge([make(tmp_path, "a.musicxml", notes)])
    check = score_xml.check(tree)[0]
    assert check.ok and check.notes == 1


def test_titles_go_where_musicxml2ly_looks(tmp_path):
    tree = score_xml.merge([make(tmp_path, "a.musicxml")])
    score_xml.set_titles(tree, title="Overture", part_name="Perc", composer="Glinka")
    text = ET.tostring(tree.getroot(), encoding="unicode")
    assert "<work-title>Overture</work-title>" in text
    assert "<part-name>Perc</part-name>" in text
    assert 'type="composer">Glinka' in text


def test_merging_nothing_is_an_error():
    with pytest.raises(ValueError):
        score_xml.merge([])


def test_a_bars_rest_counts_as_a_full_bar(tmp_path):
    # MusicXML writes a whole-bar rest — and a multi-bar rest — with
    # measure="yes"; its duration may say seven bars' worth.
    notes = '<note><rest measure="yes"/><duration>56</duration></note>'
    tree = score_xml.merge([make(tmp_path, "a.musicxml", notes)])
    assert score_xml.check(tree)[0].ok


def test_nonsense_divisions_do_not_take_the_checker_down(tmp_path):
    path = tmp_path / "bad.musicxml"
    path.write_text(SCORE.format(notes=FULL_BAR).replace(
        "<divisions>2</divisions>", "<divisions>0</divisions>"))
    tree = score_xml.merge([path])
    assert score_xml.check(tree)  # no ZeroDivisionError


def test_an_unmatched_tuplet_is_repaired(tmp_path):
    notes = (FULL_BAR.replace("</note>",
             '<notations><tuplet type="stop" number="1"/></notations></note>'))
    tree = score_xml.merge([make(tmp_path, "a.musicxml", notes)])
    repairs = score_xml.sanitize(tree)
    assert repairs and "stopped without starting" in repairs[0]
    assert not tree.getroot().findall(".//tuplet")


def test_a_note_with_no_duration_and_no_type_is_dropped(tmp_path):
    notes = FULL_BAR + "<note><rest/></note>"
    tree = score_xml.merge([make(tmp_path, "a.musicxml", notes)])
    repairs = score_xml.sanitize(tree)
    assert any("no duration and no type" in r for r in repairs)
    assert len(tree.getroot().findall(".//note")) == 1


def test_divisions_of_zero_are_replaced_from_the_rest_of_the_score(tmp_path):
    good = make(tmp_path, "good.musicxml")
    bad = tmp_path / "bad.musicxml"
    bad.write_text(SCORE.format(notes=FULL_BAR).replace(
        "<divisions>2</divisions>", "<divisions>0</divisions>"))
    tree = score_xml.merge([good, bad])
    repairs = score_xml.sanitize(tree)
    assert any("divisions was 0, set to 2" in r for r in repairs)


TWO_STAFF_SCORE = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list>
    <part-group type="start" number="1"/>
    <score-part id="P1"><part-name>Flute</part-name></score-part>
    <score-part id="P2"><part-name>Piano</part-name></score-part>
    <score-part id="P3"><part-name>Perc</part-name></score-part>
    <part-group type="stop" number="1"/>
  </part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes></measure></part>
  <part id="P2"><measure number="1"><attributes><divisions>1</divisions><staves>2</staves></attributes></measure></part>
  <part id="P3"><measure number="1"><attributes><divisions>1</divisions></attributes></measure></part>
</score-partwise>
"""


def two_staff(tmp_path):
    path = tmp_path / "score.musicxml"
    path.write_text(TWO_STAFF_SCORE)
    return score_xml.read(path)


def test_staff_spans_count_staves_not_parts(tmp_path):
    assert score_xml.staff_spans(two_staff(tmp_path)) == [
        ("P1", 0, 1), ("P2", 1, 2), ("P3", 3, 1),
    ]


def test_the_bottom_staff_is_found_through_a_two_staff_part(tmp_path):
    # Counting parts would give the piano; counting staves gives the percussion.
    chosen = score_xml.select_staff(two_staff(tmp_path), -1)
    assert [p.get("id") for p in chosen.getroot().findall("part")] == ["P3"]
    assert [sp.get("id") for sp in chosen.getroot().findall(".//score-part")] == ["P3"]
    # The bracket that grouped the parts must not be left behind.
    assert not chosen.getroot().findall(".//part-group")


def test_selecting_a_middle_staff_of_a_grand_staff_takes_the_whole_part(tmp_path):
    for index in (1, 2):
        chosen = score_xml.select_staff(two_staff(tmp_path), index)
        assert [p.get("id") for p in chosen.getroot().findall("part")] == ["P2"]


def test_selecting_a_staff_that_is_not_there_says_so(tmp_path):
    with pytest.raises(ValueError, match="staff 9"):
        score_xml.select_staff(two_staff(tmp_path), 9)


def test_a_bar_rest_that_is_not_a_bar_long_is_corrected(tmp_path):
    # Audiveris writes 36 where the bar is 24 (divisions 2, 4/4 -> 8 here).
    notes = '<note><rest measure="yes"/><duration>12</duration></note>'
    tree = score_xml.merge([make(tmp_path, "a.musicxml", notes)])
    repairs = score_xml.sanitize(tree)
    assert any("bar rest lasted 12 where the bar is 8" in r for r in repairs)
    assert tree.getroot().findtext(".//note/duration") == "8"


TWO_VOICES = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Perc</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><voice>1</voice><duration>8</duration><type>whole</type></note>
      <backup><duration>8</duration></backup>
      <note><voice>2</voice><duration>8</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""


def test_two_voices_are_one_bar_not_two(tmp_path):
    # 73 bars of the real percussion part carry a second voice; adding up every
    # duration counted each of them twice and called them all broken.
    path = tmp_path / "voices.musicxml"
    path.write_text(TWO_VOICES)
    tree = score_xml.merge([path])
    check = score_xml.check(tree)[0]
    assert check.ok, (check.beats, check.expected)
    assert score_xml.measure_length(tree.getroot().find(".//measure")) == 8


def test_a_two_voice_bar_is_not_padded(tmp_path):
    path = tmp_path / "voices.musicxml"
    path.write_text(TWO_VOICES)
    tree = score_xml.merge([path])
    assert score_xml.fill_incomplete(tree) == []


def _part_with_rests():
    """A page's worth of MusicXML shaped the way Audiveris writes one: two
    systems, and a multi-measure rest written out expanded."""
    import xml.etree.ElementTree as ET

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    part.set("id", "P1")

    def bar(number, *, new_system=False, rest=0, note=False):
        measure = ET.SubElement(part, "measure")
        measure.set("number", str(number))
        if new_system:
            printing = ET.SubElement(measure, "print")
            printing.set("new-system", "yes")
        attributes = ET.SubElement(measure, "attributes")
        ET.SubElement(attributes, "divisions").text = "4"
        time = ET.SubElement(attributes, "time")
        ET.SubElement(time, "beats").text = "4"
        ET.SubElement(time, "beat-type").text = "4"
        if rest:
            style = ET.SubElement(attributes, "measure-style")
            ET.SubElement(style, "multiple-rest").text = str(rest)
        item = ET.SubElement(measure, "note")
        if note:
            pitch = ET.SubElement(item, "pitch")
            ET.SubElement(pitch, "step").text = "C"
            ET.SubElement(pitch, "octave").text = "4"
        else:
            ET.SubElement(item, "rest").set("measure", "yes")
        ET.SubElement(item, "duration").text = "16"
        return measure

    bar(1, note=True)
    bar(2, rest=3)
    bar(3)
    bar(4)
    bar(5, new_system=True, note=True)
    bar(6, note=True)
    return ET.ElementTree(root)


def test_a_system_is_where_the_scan_broke_the_line():
    from sheeets.score_xml import systems_of

    assert systems_of(_part_with_rests()) == [(0, 4), (4, 6)]


def test_the_printed_bars_are_fewer_than_the_measures():
    """A three-bar rest is one bar on the page and three in the recognition."""
    from sheeets.score_xml import written_bars

    tree = _part_with_rests()
    assert written_bars(tree, (0, 4)) == [(0, None), (1, 3)]


def test_lengthening_a_rest_adds_the_bars_behind_it():
    from sheeets.score_xml import count_measures, set_multi_rest, written_bars

    tree = _part_with_rests()
    assert set_multi_rest(tree, 1, 13) == 10
    assert count_measures(tree) == 16
    assert written_bars(tree, (0, 14)) == [(0, None), (1, 13)]


def test_a_rest_the_engine_missed_can_be_put_back():
    from sheeets.score_xml import count_measures, make_multi_rest, written_bars

    tree = _part_with_rests()
    # Measure 0 is a note on the page it came from; the page says it is a
    # five-bar rest, and a rest has no content beyond its length.
    assert make_multi_rest(tree, 0, 5) == 4
    assert count_measures(tree) == 10
    assert written_bars(tree, (0, 8))[0] == (0, 5)


def test_bars_that_cannot_be_recovered_are_still_counted():
    from sheeets.score_xml import count_measures, pad_system

    tree = _part_with_rests()
    assert pad_system(tree, (4, 6), 3) == 3
    assert count_measures(tree) == 9


def test_words_printed_on_the_page_are_not_words_to_sing():
    import xml.etree.ElementTree as ET

    from sheeets.score_xml import strip_stray_lyrics

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    for n in range(40):
        measure = ET.SubElement(part, "measure")
        measure.set("number", str(n + 1))
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "duration").text = "4"
        if n in (10, 11, 12):                    # the publisher's imprint
            lyric = ET.SubElement(note, "lyric")
            ET.SubElement(lyric, "text").text = ["VERLAG", "AG,", "4537"][n - 10]
    tree = ET.ElementTree(root)
    notes = strip_stray_lyrics(tree)
    assert notes and "VERLAG" in notes[0]
    assert not list(tree.getroot().iter("lyric"))


def test_a_part_that_really_has_words_keeps_them():
    import xml.etree.ElementTree as ET

    from sheeets.score_xml import strip_stray_lyrics

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    for n in range(10):
        measure = ET.SubElement(part, "measure")
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "duration").text = "4"
        lyric = ET.SubElement(note, "lyric")
        ET.SubElement(lyric, "text").text = "la"
    tree = ET.ElementTree(root)
    strip_stray_lyrics(tree)
    assert len(list(tree.getroot().iter("lyric"))) == 10


def test_the_same_marking_is_not_printed_twice():
    import xml.etree.ElementTree as ET

    from sheeets.score_xml import dedupe_directions

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    measure = ET.SubElement(part, "measure")
    for text in ("Presto", "Presto", "solo"):
        direction = ET.SubElement(measure, "direction")
        kind = ET.SubElement(direction, "direction-type")
        ET.SubElement(kind, "words").text = text
    assert dedupe_directions(ET.ElementTree(root)) == 1
    assert [w.text for w in root.iter("words")] == ["Presto", "solo"]


def test_a_bar_rest_inside_a_multi_rest_is_made_visible():
    """Invisible whole-bar rests come out of musicxml2ly as spacers, so a
    sixteen-bar rest prints as sixteen empty bars instead of one marked 16."""
    import xml.etree.ElementTree as ET

    from sheeets.score_xml import show_bar_rests

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    measure = ET.SubElement(part, "measure")
    note = ET.SubElement(measure, "note")
    note.set("print-object", "no")
    ET.SubElement(note, "rest").set("measure", "yes")
    sounding = ET.SubElement(measure, "note")
    sounding.set("print-object", "no")           # a cue or an invisible note
    ET.SubElement(sounding, "pitch")
    tree = ET.ElementTree(root)
    assert show_bar_rests(tree) == 1
    assert "print-object" not in note.attrib
    assert sounding.get("print-object") == "no"  # only whole-bar rests


def _bare(duration, divisions=12, rest=True):
    import xml.etree.ElementTree as ET

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    measure = ET.SubElement(part, "measure")
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(divisions)
    note = ET.SubElement(measure, "note")
    if rest:
        ET.SubElement(note, "rest")
    else:
        ET.SubElement(note, "pitch")
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    return ET.ElementTree(root), note


def test_a_rest_with_a_length_and_no_value_is_named():
    """musicxml2ly dies part-way through the file on one of these, and the
    message names LilyPond's own internals rather than the bar."""
    from sheeets.score_xml import name_durations

    tree, note = _bare(6)                     # 6 of 12 divisions: an eighth
    assert name_durations(tree)
    assert note.findtext("type") == "eighth" and note.find("dot") is None
    assert note.findtext("duration") == "6"


def test_a_dotted_length_gets_its_dot():
    from sheeets.score_xml import name_durations

    tree, note = _bare(18)                    # a dotted quarter
    name_durations(tree)
    assert note.findtext("type") == "quarter"
    assert len(note.findall("dot")) == 1


def test_a_length_no_note_can_be_is_cut_and_said_so():
    from sheeets.score_xml import name_durations

    tree, note = _bare(20)                    # five sixths of a bar
    notes = name_durations(tree)
    assert note.findtext("type") == "quarter" and len(note.findall("dot")) == 1
    assert note.findtext("duration") == "18"
    assert any("cut to the longest" in n for n in notes)


def test_a_quote_in_a_marking_does_not_end_the_lilypond_string():
    import xml.etree.ElementTree as ET

    from sheeets.score_xml import tame_text

    root = ET.Element("score-partwise")
    words = ET.SubElement(ET.SubElement(root, "direction"), "words")
    words.text = 'A"egro m0 to al \\ways'
    notes = tame_text(ET.ElementTree(root))
    assert words.text == "A'egro m0 to al ways"
    assert notes


def test_a_bar_the_filler_pads_still_says_what_rest_it_is():
    """A rest with a length and no written value is what musicxml2ly dies on,
    so the filler must not create one — it did, and put the crash back."""
    import xml.etree.ElementTree as ET

    from sheeets.score_xml import fill_incomplete

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    measure = ET.SubElement(part, "measure")
    measure.set("number", "1")
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = "12"
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = "4"
    ET.SubElement(time, "beat-type").text = "4"
    note = ET.SubElement(measure, "note")
    ET.SubElement(note, "pitch")
    ET.SubElement(note, "duration").text = "36"        # three beats of four
    ET.SubElement(note, "type").text = "half"

    assert fill_incomplete(ET.ElementTree(root))
    padding = measure.findall("note")[-1]
    assert padding.find("rest") is not None
    assert padding.findtext("type") == "quarter"
