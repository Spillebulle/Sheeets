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
