"""Making the recognition agree with what the page prints about itself.

An engraved part carries two numbers a machine can check itself against: the
bar number over each system, and the count over each multi-measure rest.
`sheeets.barnum` reads them off the page; this is what is then done with them.

The order of the argument matters more than any single step:

1. Are these numbers a numbering at all, or a scatter of digit-shaped ink?
2. Does any one of them make nonsense of the systems either side of it?
3. For a system where the page and the recognition disagree, can the page's
   own multi-measure rests account for the difference exactly?
4. If not, the bars still have to be counted, so they go in as rests and are
   named for proofreading — because a part whose bar numbers do not match the
   conductor's score cannot be used at a rehearsal at all.

Every step can refuse, and refusing is the normal outcome for a part with no
numbers on it.  Nothing here changes a note; it changes how long a rest lasts
and how many bars a system holds, and it says out loud each time it does.
"""

from __future__ import annotations

from . import score_xml
from .model import Extraction


def staves_by_page(extraction: Extraction) -> dict[int, int]:
    """Which staff of each page the part is being cut from.

    The multi-measure rests have to be read on *that* staff.  A bar number does
    not: it is printed once over the top of the system and it counts the same
    bars for every instrument under it, which is why this works on a score and
    not only on a part.
    """
    return {
        segment.band.page_index: segment.band.staff_index
        for segment in extraction.segments
    }


def _fit_counts(read: list[int | None], target: int) -> tuple[list[int] | None, str]:
    """Make the multi-measure rest counts add up to what the page demands.

    The total is not in doubt: the difference between two printed bar numbers
    is exactly how many bars the system holds, so once the written bars are
    counted the rests' total is forced.  Every count read off the page is then
    checked against it, which turns a pile of small OCR answers into one
    arithmetic question with a right answer.

    One unreadable count is solved for.  One *wrong* count can also be solved
    for, but only when a single position can be changed to fix the sum and the
    new value looks like a misreading of what was read there — 4 for 44, 3 for
    8 — rather than an unrelated number.  Anything less certain is refused and
    reported, because a part with a rest of the wrong length is worse than a
    part that says it does not know.
    """
    if not read:
        return ([], "") if target == 0 else (None, "there are no multi-bar rests")
    blanks = [i for i, count in enumerate(read) if count is None]
    known = sum(count for count in read if count is not None)
    if len(blanks) > 1:
        return None, f"{len(blanks)} of its multi-bar rests could not be read"
    if len(blanks) == 1:
        value = target - known
        if value < 2:
            return None, "the unreadable multi-bar rest would have to be under two bars"
        out = [value if count is None else count for count in read]
        return out, f"one multi-bar rest could not be read; the bar numbers make it {value}"
    counts = [int(count) for count in read]
    if sum(counts) == target:
        return counts, ""
    fixes = []
    for i, count in enumerate(counts):
        value = target - (sum(counts) - count)
        if 2 <= value <= 200 and _plausible_misread(str(count), str(value)):
            fixes.append((i, value))
    if len(fixes) == 1:
        i, value = fixes[0]
        out = list(counts)
        was = out[i]
        out[i] = value
        return out, f"a multi-bar rest read as {was}; the bar numbers make it {value}"
    return None, (f"its multi-bar rests {counts} add up to {sum(counts)} "
                  f"where the bar numbers want {target}")


def _plausible_misread(read: str, wanted: str) -> bool:
    """Could `wanted` have been read as `read` by an OCR of small digits?"""
    if read == wanted:
        return True
    if wanted in read or read in wanted:       # 4 read as 44, 27 read as 2
        return True
    if len(read) == len(wanted):               # one digit confused for another
        return sum(a != b for a, b in zip(read, wanted)) == 1
    return False


def reconcile(tree, facts, wanted, page_index: int,
              shaky: set[int] | None = None,
              used: list | None = None) -> list[str]:
    """Make the recognised bars agree with the numbers printed on the page.

    An engine reads a multi-measure rest by reading the number over it, and
    that is the number it is worst at: measured on a publisher's timpani part,
    every two-digit count came back with its tens digit missing — 16 as 6, 24
    as 4, 34 as 4 — so a 401-bar part was recognised as 255 bars.  Nothing
    inside the MusicXML can notice that.  The printed bar numbers can, because
    the difference between two of them is exactly how many bars lie between.

    So: where the page says a system holds N bars and the recognition produced
    a different number, and the page's own multi-measure rests can account for
    the difference, the rests are set to what the page says.  Where they cannot,
    nothing is changed and the disagreement is reported — a part that says it
    is unsure is worth more than one that quietly invents bars.

    `shaky` collects the systems whose bars could **not** be lined up, and it
    matters to more than the report.  Where bars had to be invented the total
    is right and the places inside the system are not, so anything positioned
    by bar within that system is positioned wrongly.  Measured on a timpani
    part: system 6 holds 98 bars and gets 98, but as one 73-bar rest at the
    end instead of the page's 4, 16, 24, 14, 34 and 3 — and the four rehearsal
    letters printed over those rests then landed on bars 65, 71, 72 and 76
    where the page has 82, 106, 120 and 154.  A player trusts a letter, so a
    letter in the wrong bar is worse than no letter.  `-1` means the whole
    page.
    """
    shaky = shaky if shaky is not None else set()
    if used is not None:
        used[:] = []
    if not facts:
        return []
    notes: list[str] = []
    mine = [f for f in facts if f.page_index == page_index]
    spans = score_xml.systems_of(tree)
    if len(mine) != len(spans):
        joined = align_spans(mine, spans, tree)
        if joined is None:
            shaky.add(-1)
            return [f"page {page_index + 1}: the scan shows {len(mine)} system(s) and "
                    f"the recognition {len(spans)}; the printed bar numbers were not "
                    f"used"]
        notes.append(f"page {page_index + 1}: the scan shows {len(mine)} system(s) and "
                     f"the recognition {len(spans)}; lined up by how many bars each "
                     f"holds")
        spans = joined
    if used is not None:
        used[:] = spans
    for fact, span in reversed(list(zip(mine, spans))):
        want = wanted.get((fact.page_index, fact.system_index))
        if want is None:
            continue
        printed = score_xml.written_bars(tree, span)
        where = f"page {page_index + 1} system {fact.system_index + 1}"
        if span[1] - span[0] == want:
            continue
        if not _page_agrees(want, fact):
            # The bar numbers are read, and a misread one is a plausible
            # number in the wrong place: "14" read as "4" on a score page makes
            # the page before it three bars long and the page after it
            # twenty-four, and both would be "repaired" into the part.  The
            # barlines are an independent witness — they were counted off the
            # same page before any of this — so a span they contradict is not
            # acted on at all.
            notes.append(f"{where}: the bar numbers say {want} bar(s) and the "
                         f"barlines on the page say about {fact.written}; "
                         f"the numbers are not used here")
            shaky.add(fact.system_index)
            continue
        if len(printed) != fact.written:
            notes.append(f"{where}: the page has {fact.written} written bar(s) and the "
                         f"recognition {len(printed)}; the printed bar numbers say "
                         f"{want} bar(s) but nothing could be lined up")
            shaky.add(fact.system_index)
            _pad(tree, span, want, where, notes)
            continue
        counts, note = _fit_counts(fact.rests, want - len(printed) + len(fact.rests))
        if counts is None:
            notes.append(f"{where}: the page says {want} bar(s) and "
                         f"{span[1] - span[0]} were read, but {note}")
            shaky.add(fact.system_index)
            _pad(tree, span, want, where, notes)
            continue
        if note:
            notes.append(f"{where}: {note}")
        by_bar = dict(zip(fact.rest_bars, counts))
        for bar in reversed(range(len(printed))):
            index, was = printed[bar]
            now = by_bar.get(bar)
            if now == was:
                continue
            if now is None:
                notes.append(f"{where}: bar {bar + 1} was read as a rest of {was} bar(s) "
                             f"and the page shows no such rest — cut to one bar, check it")
                score_xml.set_multi_rest(tree, index, 1)
            elif was is None:
                notes.append(f"{where}: bar {bar + 1} is a {now}-bar rest on the page "
                             f"and was not read as one — put back")
                score_xml.make_multi_rest(tree, index, now)
            else:
                notes.append(f"{where}: a multi-bar rest read as {was}, "
                             f"the page prints {now}")
                score_xml.set_multi_rest(tree, index, now)
    return notes


def align_spans(facts, spans, tree, most: int = 3, spare: int = 2,
                spare_cost: float = 1.0):
    """Match the systems the page shows to the systems the recognition made.

    They are not always the same count.  Audiveris splits a printed system in
    two, or the detector loses one off a crooked page, and the answer used to
    be to throw the whole page's bar numbers away: "the scan shows 13
    system(s) and the recognition 14; the printed bar numbers were not used".
    That discards the only outside evidence the page offers, and on one part it
    also discarded ten rehearsal letters that had been read correctly.

    The two sequences can be lined up by what they are made of.  Each system
    the page shows holds a known number of *printed* bars, counted from its
    barlines; each recognised span holds a countable number too.  Both run in
    the same order, so this is an alignment and not a matching: a page system
    may take up to `most` recognised spans (the engine split it), and up to
    `spare` recognised spans may be left out altogether (the page's own system
    was never detected).  Measured on the crooked scan in the fleet, whose
    thirteen detected systems hold 10, 7, 6, 5, 5, 7, 7, 7, 9, 8, 7, 6 and 7
    bars against the recognition's fourteen at 9, 10, 7, 5, 5, 5, 6, 7, 7, 8,
    8, 7, 6, 6: leaving out the recognition's *first* span lines the rest up
    with a disagreement of four bars in ninety, where pairing them off one for
    one disagrees by thirteen.

    Returns one span per page system, or None where the answer would be a
    guess: nothing is accepted unless it is at least twice as good as pairing
    them off as far as they go.
    """
    if not facts or not spans or len(facts) > len(spans):
        return None
    printed = [len(score_xml.written_bars(tree, span)) for span in spans]
    rows, columns = len(facts), len(spans)
    if columns - rows > spare + rows * (most - 1):
        return None
    big = float("inf")
    # cost[i][j][k]: i page systems and j spans used, k of them left out.
    cost = [[[big] * (spare + 1) for _ in range(columns + 1)] for _ in range(rows + 1)]
    back = [[[None] * (spare + 1) for _ in range(columns + 1)] for _ in range(rows + 1)]
    cost[0][0][0] = 0.0
    for i in range(rows + 1):
        for j in range(columns + 1):
            for k in range(spare + 1):
                if cost[i][j][k] == big:
                    continue
                here = cost[i][j][k]
                if j < columns and k < spare:          # leave this span out
                    if here + spare_cost < cost[i][j + 1][k + 1]:
                        cost[i][j + 1][k + 1] = here + spare_cost
                        back[i][j + 1][k + 1] = (i, j, k, 0)
                if i < rows:
                    for take in range(1, min(most, columns - j) + 1):
                        was = abs(sum(printed[j:j + take]) - facts[i].written)
                        if here + was < cost[i + 1][j + take][k]:
                            cost[i + 1][j + take][k] = here + was
                            back[i + 1][j + take][k] = (i, j, k, take)
    best, at = big, None
    for k in range(spare + 1):
        if cost[rows][columns][k] < best:
            best, at = cost[rows][columns][k], k
    if at is None:
        return None
    plain = sum(abs(printed[i] - facts[i].written) for i in range(rows))
    if best * 2 > plain and rows != columns:
        return None                      # no better than pairing them off
    out: list[tuple[int, int]] = []
    i, j, k = rows, columns, at
    while back[i][j][k] is not None:
        pi, pj, pk, take = back[i][j][k]
        if take:
            out.append((spans[pj][0], spans[pj + take - 1][1]))
        i, j, k = pi, pj, pk
    out.reverse()
    return out if len(out) == rows else None


def _pad(tree, span, want: int, where: str, notes: list[str]) -> None:
    """Keep the bar count right even when the bars themselves are lost."""
    short = want - (span[1] - span[0])
    if short > 0:
        score_xml.pad_system(tree, span, short)
        notes.append(f"{where}: {short} bar(s) the page has and the recognition does "
                     f"not; put in as rests so the numbering stays right — proofread them")


def drop_what_the_page_denies(facts) -> list[str]:
    """Throw away a bar number that makes nonsense of the systems around it.

    A misread number is a plausible number in the wrong place, and it spoils
    *two* spans, not one: "14" read as "4" on a score page makes the page
    before it three bars long and the page after it twenty-four.  Both are
    contradicted by the barlines on those pages, and a number contradicted on
    both sides is the number that is wrong.

    One side failing is not enough — the last system of a page legitimately
    disagrees when the barline count is poor — so both are required.
    """
    notes: list[str] = []
    known = [f for f in facts if f.number is not None]
    for before, here, after in zip(known, known[1:], known[2:]):
        if None in (before.number, here.number, after.number):
            continue                      # one of them has already been dropped
        incoming = here.number - before.number
        outgoing = after.number - here.number
        if incoming > 0 and _page_agrees(incoming, before):
            continue
        if outgoing > 0 and _page_agrees(outgoing, here):
            continue
        notes.append(f"bar number {here.number} on page {here.page_index + 1}: "
                     f"the pages either side of it do not hold {incoming} and "
                     f"{outgoing} bars; dropped")
        here.number = None
    return notes


def _page_agrees(want: int, fact, slack: float = 0.2) -> bool:
    """Does the barline count support what the bar numbers claim?

    The test is deliberately **one-sided**, and getting that wrong cost a
    timpani part seventy-three bars.  The first version worked out how many
    bars the system ought to hold by adding up the multi-measure rest counts
    that had been read off it, and compared that with the barlines.  But the
    rest counts are the *unreliable* half — Audiveris drops the tens digit off
    them, which is the fault the whole reconciliation exists to repair — so
    the check was asking the suspect to vouch for the witness.  System 6 of
    that part reads its rests as 44, 16, ?, 14, 34 and 3, which is at least a
    hundred and eleven bars; the printed numbers say the system holds
    ninety-eight; and the span was thrown out for disagreeing with counts
    that were about to be corrected against it.

    What the barlines *can* say is how much paper there is, and that only ever
    puts a floor under the number of bars:

    - fewer bars than the system has written barlines is impossible, whatever
      the rests say, so a number that claims that is misread;
    - more bars than the barlines is what a multi-measure rest is for, so it
      is only suspicious where the system has **no** rest on it at all.

    Counting barlines is itself an estimate — about three per cent over on a
    nineteen-stave score — so both edges are given slack.  This is not here to
    check arithmetic; `_fit_counts` does that, against the numbers.  It is
    here to catch a bar number read as something else entirely.
    """
    if not fact.written:
        return False
    room = max(2, slack * fact.written)
    if want < fact.written - room:
        return False
    if not fact.rests and want > fact.written + room:
        return False
    return True


def numbers_are_worth_using(facts, share: float = 0.6, least: int = 3) -> bool:
    """Does this part actually print bar numbers?

    Many do not, and a part that does not still offers a few digit-shaped
    things above its staves — a page number, a fingering, a smudge.  On the
    worst scan in the fleet, a 77-measure part with no numbers at all yielded
    five readings, two of them the same "1" on different pages, and the run
    chosen from them said the part was twelve bars long.  That number then
    replaced a barline count that was roughly right, and — far worse — would
    have been used to "repair" the recognition against.

    So the numbers are used only when most of the systems carry one.  A part
    that numbers its systems numbers all of them; a scatter of readings across
    a third of the page is not a numbering, it is noise.
    """
    if not facts:
        return False
    read = [f for f in facts if f.number is not None]
    return len(read) >= least and len(read) >= share * len(facts)


def bars_from_numbers(facts, wanted) -> dict[int, int]:
    """Bars per page, taken from the numbers printed on the part.

    Counting barlines is an estimate — it made 414 of a part of 401 bars.  The
    printed numbers are not an estimate: the difference between two of them is
    the answer, and it holds across a system whose own number was not read,
    because the bars are still between the two that were.  They are counted
    against the page the earlier number is on, which is where all but the last
    of them are.

    The last system has no successor to be subtracted from, so its own written
    bars and rests are used.  That is the only guess here and it is confined to
    one system.
    """
    known = [f for f in facts if f.number is not None]
    if len(known) < 2:
        return {}
    out: dict[int, int] = {}
    for this, following in zip(known, known[1:]):
        out[this.page_index + 1] = out.get(this.page_index + 1, 0) + (
            following.number - this.number
        )
    last = facts[-1]
    tail = last.written - len(last.rests) + sum(c or 0 for c in last.rests)
    if last.number is not None and last is not known[-1]:
        tail = 0
    out[last.page_index + 1] = out.get(last.page_index + 1, 0) + max(0, tail)
    return out
