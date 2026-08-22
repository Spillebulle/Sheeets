"""Splitting a book of parts, using headers as the real ones came out of OCR."""

from sheeets.book import (
    PartRange, find_title, letters, name_from, starts_a_part, split,
)

# Verbatim from a 32-page brass band book: the good, the mangled and the junk.
HEADERS = {
    0: "?\nRULE BRITANNIA.\nSoloist\nCornet in B: by John Hartmann.",
    1: "ss dali, Cornet tn B?\n= ' er 3 =\" = =",
    2: "ee Cornet in Bb :\n{ : aa EES we ee ae",
    3: 'Soprano RULE B RITANNIA” J. HARTMANN\nband arrangement D.S. Stephens',
    4: 'Solo Cornet “RULE BRITANNIA” ys armann\nband arrangement',
    5: "optevt I an. -\n~ twe = tl > >>",
    6: 'Repiano Cornet * RULE B RITANNIA” J. HARTMANN',
    7: '2nd Cornet “RULE BRITANNIA” J. HARTMANN',
    8: "7s\na ce No _",
    11: 'Fuge! Horn “RULE BRITANNIA” sr utarrmann',
    12: 'Solo Horn “RULE BRI -',
    14: 'Ist Horn “RULE BRITANNIA” ss atartmann',
    19: 'dad Baritone “RULE BRITANNIA” sy uaerwans',
    26: 'Bass Eb “RULE BRITANNIA” J. HARTMANN',
    28: 'Bass Bh “RULE BRITANNIA” ss nartmann',
}


def test_the_title_is_found_inside_the_lines_that_carry_it():
    # It never appears as a line of its own on a part's first page — it shares
    # the line with the player and the composer.
    assert find_title(HEADERS) == "rulebritannia"


def test_letters_makes_the_ocr_mangling_harmless():
    assert letters('“RULE B RITANNIA”') == letters("RULE BRITANNIA.")


def test_a_first_page_is_told_from_a_continuation():
    title = find_title(HEADERS)
    for index in (0, 3, 4, 6, 7, 11, 14, 19, 26, 28):
        assert starts_a_part(HEADERS[index], title), index
    for index in (1, 2, 5, 8):
        assert not starts_a_part(HEADERS[index], title), index


def test_a_truncated_title_still_starts_a_part():
    """"Solo Horn “RULE BRI -" — one part of twenty was swallowed by this."""
    assert starts_a_part(HEADERS[12], find_title(HEADERS))


def test_names_come_out_readable_despite_the_ocr():
    title = find_title(HEADERS)
    assert name_from(HEADERS[0], title) == "Soloist"
    assert name_from(HEADERS[7], title) == "2nd Cornet"
    assert name_from(HEADERS[11], title) == "Flugel Horn"
    assert name_from(HEADERS[14], title) == "1st Horn"
    assert name_from(HEADERS[19], title) == "2nd Baritone"


def test_the_pitch_stays_in_the_name():
    # "Bass Eb" and "Bass Bb" are different players.
    title = find_title(HEADERS)
    assert name_from(HEADERS[26], title) == "Bass Eb"
    assert name_from(HEADERS[28], title) == "Bass Bb"


def test_ranges_run_to_the_page_before_the_next_part():
    part = PartRange(name="Solo Cornet", first_page=5, last_page=6)
    assert part.pages == "5-6" and part.count == 2


def test_a_book_with_no_headers_at_all_reports_nothing_rather_than_guessing():
    class FakePage:
        def __init__(self):
            self.staves = []
    assert split([]).parts == []
