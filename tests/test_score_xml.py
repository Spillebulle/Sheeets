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
