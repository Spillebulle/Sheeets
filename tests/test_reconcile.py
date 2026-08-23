"""What the page's own numbers are allowed to overrule, and what overrules them.

The reconciliation has two witnesses to the same question and they disagree:
the bar numbers printed on the page, and the barlines counted off it.  These
tests are about which one is believed where, because getting that backwards is
not a small error — it silently drops bars out of the middle of a part.
"""

def _facts(number, written, rests=()):
    from sheeets.barnum import SystemFacts

    return SystemFacts(page_index=0, system_index=5, number=number,
                       rests=list(rests), rest_bars=list(range(len(rests))),
                       written=written)


def test_the_barlines_only_put_a_floor_under_the_bar_numbers():
    """System 6 of a timpani part reads its rests as 44, 16, ?, 14, 34 and 3
    — at least a hundred and eleven bars — while the printed numbers say the
    system holds ninety-eight.  The first version of this test added the read
    counts up and threw the span out for disagreeing with them, which is the
    suspect vouching for the witness: those counts are the thing about to be
    corrected against the numbers.  It cost the part seventy-three bars."""
    from sheeets.reconcile import _page_agrees

    assert _page_agrees(98, _facts(59, written=9, rests=[44, 16, None, 14, 34, 3]))


def test_a_number_claiming_fewer_bars_than_the_page_has_barlines_is_refused():
    """"14" read as "4" makes the page before it three bars long, and three
    bars cannot be printed as nine."""
    from sheeets.reconcile import _page_agrees

    assert not _page_agrees(3, _facts(4, written=9, rests=[2]))


def test_more_bars_than_the_paper_holds_needs_a_rest_to_hide_them_in():
    from sheeets.reconcile import _page_agrees

    assert not _page_agrees(24, _facts(4, written=9))       # nowhere to put them
    assert _page_agrees(24, _facts(4, written=9, rests=[None]))


def test_a_system_with_no_barline_count_says_nothing_either_way():
    from sheeets.reconcile import _page_agrees

    assert not _page_agrees(8, _facts(1, written=0))


def _tree(measures: int):
    import xml.etree.ElementTree as ET

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    for n in range(measures):
        measure = ET.SubElement(part, "measure")
        measure.set("number", str(n + 1))
        if n == 0:
            ET.SubElement(measure, "print").set("new-system", "yes")
    return ET.ElementTree(root)


def test_a_letter_is_not_placed_in_a_system_whose_bars_did_not_line_up():
    """Its total is right and its insides are not. Measured on a timpani part:
    system 6's ninety-eight bars came out as one seventy-three-bar rest at the
    end instead of the page's 4, 16, 24, 14, 34 and 3, and C, D, E and F
    landed on bars 65, 71, 72 and 76 where the page has 82, 106, 120 and 154.
    A player trusts a letter."""
    from sheeets.retype import _place_marks

    tree = _tree(8)
    placed, note = _place_marks(tree, [(0, 1, "A"), (0, 4, "B")], shaky={0})
    assert placed == 0
    assert "could not be lined up" in note
    assert not list(tree.getroot().iter("rehearsal"))

    placed, note = _place_marks(tree, [(0, 1, "A"), (0, 4, "B")], shaky=set())
    assert placed == 2 and note == ""


def test_letters_that_share_a_bar_or_come_out_of_order_are_all_refused():
    """On the worst photocopy in the fleet the recognition is ten bars short
    of the page, so G and H both clamped to the last bar of their system and
    were engraved on top of each other."""
    from sheeets.retype import _place_marks

    tree = _tree(4)
    placed, note = _place_marks(tree, [(0, 9, "G"), (0, 9, "H")], shaky=set())
    assert placed == 0
    assert "shared a bar or come out of order" in note


class _Fact:
    def __init__(self, written):
        self.written = written


def _spans_tree(per_span):
    """A tree whose systems hold the given numbers of printed bars."""
    import xml.etree.ElementTree as ET

    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    n = 0
    for bars in per_span:
        for b in range(bars):
            measure = ET.SubElement(part, "measure")
            measure.set("number", str(n + 1))
            n += 1
            if b == 0:
                ET.SubElement(measure, "print").set("new-system", "yes")
    from sheeets import score_xml

    tree = ET.ElementTree(root)
    return tree, score_xml.systems_of(tree)


def test_a_system_the_engine_split_in_two_is_put_back_together():
    """Audiveris splits a printed system often enough to matter, and the
    answer used to be to throw the whole page's bar numbers away — which on
    one part also threw away ten rehearsal letters that had been read
    correctly."""
    from sheeets.reconcile import align_spans

    tree, spans = _spans_tree([4, 3, 5, 6])        # the recognition: four
    facts = [_Fact(4), _Fact(8), _Fact(6)]         # the page: three
    joined = align_spans(facts, spans, tree)
    assert joined == [(0, 4), (4, 12), (12, 18)]


def test_an_alignment_that_is_no_better_than_pairing_off_is_refused():
    from sheeets.reconcile import align_spans

    tree, spans = _spans_tree([4, 4, 4, 4])
    facts = [_Fact(9), _Fact(2), _Fact(7)]         # nothing lines up
    assert align_spans(facts, spans, tree) is None


def test_a_system_the_detector_missed_leaves_a_spare_one_in_the_recognition():
    """The crooked scan in the fleet: thirteen detected systems against the
    recognition's fourteen, and it is the *page* that lost one. Leaving out
    the recognition's first span lines the rest up with a disagreement of four
    bars in ninety, where pairing them off one for one disagrees by thirteen."""
    from sheeets.reconcile import align_spans

    tree, spans = _spans_tree([9, 10, 7, 5, 5, 5, 6, 7, 7, 8, 8, 7, 6, 6])
    facts = [_Fact(n) for n in (10, 7, 6, 5, 5, 7, 7, 7, 9, 8, 7, 6, 7)]
    joined = align_spans(facts, spans, tree)
    assert joined is not None
    assert len(joined) == 13
    assert joined[0] == spans[1]          # the spare first span is left out
    assert joined[-1] == spans[-1]
