"""Making the strip readable.

A staff in a full score is tiny — on this scan the distance between two staff
lines is 0.93 mm, where an engraved part is nearer 1.75 mm.  Cropping alone
therefore produces a part nobody wants to play from; the strip has to be
enlarged, and once enlarged it is far too wide for the paper, so each system
gets cut into pieces that are stacked down the page.

Cutting anywhere would slice through a bar.  So the cut points are barlines,
found by looking for columns of ink that run the full height of the staff and
touch both the top and the bottom line.  A note stem gets close — it can cover
85% of the staff — which is why the test is 95% *and* both end rows: with the
looser test a page of quavers offered a cut point every few centimetres.
"""

from __future__ import annotations

import numpy as np

from .model import Band, Segment


def barlines(
    band_image: np.ndarray,
    top_row: int,
    bottom_row: int,
    threshold: int = 160,
    coverage: float = 0.90,
    merge_within: int = 4,
) -> list[int]:
    """Columns (band coordinates) where a barline crosses the staff.

    Two things are being told apart, and both matter:

    * A **stem** also runs vertically through the staff, but it hangs off a
      notehead, so it reaches one outer line and not the other.  Requiring ink
      at both ends is what rejects it — without that, a bar of quavers offers a
      cut point every couple of centimetres.
    * A **printed barline** in a scan is not perfect.  Measured on page 3 of the
      score this was written against, the real barlines cover 93-95 % of the
      staff and their top pixel lands one or two rows under the fitted line.
      Testing the outermost row exactly, at 95 %, rejected three barlines in a
      row and left a 970 px stretch of music with no legal cut in it — so the
      layout cut in the middle of bar 4.

    So: measure coverage over the staff *inset* by a few rows, and look for the
    ends within a small zone rather than on one exact row.
    """
    top_row = max(0, top_row)
    bottom_row = min(band_image.shape[0] - 1, bottom_row)
    if bottom_row - top_row < 4:
        return []
    ink = band_image[top_row : bottom_row + 1] < threshold
    height = ink.shape[0]
    inset = max(1, int(round(0.08 * height)))
    fraction = ink[inset : height - inset].mean(axis=0)
    zone = inset + 1
    touches_ends = ink[:zone].any(axis=0) & ink[-zone:].any(axis=0)
    hits = np.nonzero((fraction >= coverage) & touches_ends)[0]
    if hits.size == 0:
        return []
    groups: list[list[int]] = []
    for x in hits:
        if groups and x - groups[-1][-1] <= merge_within:
            groups[-1].append(int(x))
        else:
            groups.append([int(x)])
    return [int(round(np.mean(g))) for g in groups]


def staff_spans_ink(image, top_row: int, bottom_row: int, threshold: int = 160,
                    coverage: float = 0.90) -> np.ndarray:
    """Per column: does ink cross this staff from top line to bottom line?"""
    top_row = max(0, top_row)
    bottom_row = min(image.shape[0] - 1, bottom_row)
    if bottom_row - top_row < 4:
        return np.zeros(image.shape[1], dtype=bool)
    ink = image[top_row : bottom_row + 1] < threshold
    height = ink.shape[0]
    inset = max(1, int(round(0.08 * height)))
    fraction = ink[inset : height - inset].mean(axis=0)
    zone = inset + 1
    return (fraction >= coverage) & ink[:zone].any(axis=0) & ink[-zone:].any(axis=0)


def system_barlines(
    page, system, support: float = 0.3, merge_within: int = 6
) -> list[int]:
    """Where the barlines of a whole system are, in page coordinates.

    Read on one staff, a "column of ink crossing the staff" is not only a
    barline: on a busy part a note stem does it too.  Measured across one system
    of this score, the per-staff counts ran from 11 on the percussion to 46 on a
    cornet part playing semiquavers — where the system in fact has 13 bars.

    What a barline has and a stem has not is that it crosses *the other staves
    too*, at the same place.  Counting the support across the system separates
    them: the cornet's 46 collapses to the same 13 the percussion gives, and a
    part that is cut at these places is cut where the score has its bars, not
    where this one line happens to have ink.
    """
    if not system.staves:
        return []
    width = page.image.shape[1]
    votes = np.zeros(width, dtype=np.int32)
    for staff in system.staves:
        top = int(round(staff.top))
        bottom = int(round(staff.bottom))
        spans = staff_spans_ink(page.image, top, bottom)
        votes[: spans.size] += spans.astype(np.int32)

    # Two staves must agree, which is what rejects a stem.  A system of one
    # staff is the exception and not a rare one: an extracted *part* is one
    # staff per system, and so is every publisher's part in the fleet.  There
    # is no second opinion to be had there, so take the one staff's answer —
    # the strict test in `staff_spans_ink` is all that separates a barline from
    # a stem on a part, and on a part-sized staff it does the job.  Demanding
    # two votes made the count zero, which read as "no bars in the scan".
    needed = min(len(system.staves), max(2, int(round(support * len(system.staves)))))
    hits = np.nonzero(votes >= needed)[0]
    if hits.size == 0:
        return []
    groups: list[list[int]] = []
    for x in hits:
        if groups and x - groups[-1][-1] <= merge_within:
            groups[-1].append(int(x))
        else:
            groups.append([int(x)])
    return [int(round(np.mean(g))) for g in groups]


def cut_points(
    width: int,
    max_width: int,
    barline_cols: list[int],
    start: int = 0,
    snap: float = 0.45,
) -> list[tuple[int, int]]:
    """Split [start, width) into pieces no wider than max_width, at barlines.

    The pieces are made *even* rather than greedy.  Filling each piece to the
    brim and letting the last one take what is left produced a two-bar stub at
    the end of every system — 27 of them in the score this was written against.
    Deciding how many pieces are needed first, then aiming for equal widths and
    snapping each aim to the nearest barline, gives lines that look deliberate.
    """
    span = width - start
    if max_width <= 0 or span <= max_width:
        return [(start, width)]

    pieces: list[tuple[int, int]] = []
    x = start
    while width - x > max_width:
        # Re-divide what is left on every pass, so snapping one cut early does
        # not push a stub onto the end of the line.
        remaining = width - x
        count = int(-(-remaining // max_width))  # ceil
        target = x + remaining / count
        window = snap * (remaining / count)
        reachable = [b for b in barline_cols if x < b <= x + max_width]
        near = [b for b in reachable if abs(b - target) <= window]
        # Prefer a barline near where the piece wanted to end; failing that,
        # the furthest one that still fits, because any barline beats slicing a
        # bar in half.
        if near:
            cut = int(min(near, key=lambda b: abs(b - target)))
        elif reachable:
            cut = int(max(reachable))
        else:
            cut = int(min(target, x + max_width))
        if cut <= x:
            cut = int(x + max_width)
        pieces.append((x, cut))
        x = cut
    pieces.append((x, width))
    return pieces


def scale_for(space_px: float, dpi: float, target_mm: float) -> float:
    """How much to enlarge so one staff space measures `target_mm` on paper."""
    if space_px <= 0:
        return 1.0
    current_mm = space_px / dpi * 25.4
    return target_mm / current_mm


def segments_for_band(
    band_image: np.ndarray,
    band: Band,
    top_row: int,
    bottom_row: int,
    max_source_width: int,
    dpi: float,
    keep_label_on_first: bool = True,
    barline_cols: list[int] | None = None,
) -> list[Segment]:
    """Cut one band into the pieces that will be drawn, in order.

    `barline_cols` are the system's barlines in band coordinates, which is what
    the caller should pass: they are the score's own bars.  Falling back to this
    staff's own ink is only right when the system-wide read found too little.
    """
    cols = barline_cols if barline_cols and len(barline_cols) >= 2 \
        else barlines(band_image, top_row, bottom_row)
    label_width = band.music_x0 - band.x0
    pieces = cut_points(band_image.shape[1], max_source_width, cols, start=0)
    pieces = _clear_of_markings(pieces, band_image, top_row, bottom_row, band.space)
    out: list[Segment] = []
    for i, (a, b) in enumerate(pieces):
        # Only the first piece can carry the instrument label; a continuation
        # starts inside the music and has none to drop.
        left = a
        if i == 0 and not keep_label_on_first:
            left = max(a, label_width)
        piece = band_image[:, left:b]
        if piece.size == 0 or piece.shape[0] < 2 or piece.shape[1] < 2:
            # A cut can land on the very edge of a band — a staff detected at
            # the margin of a bad scan, a chunk with nothing in it.  An empty
            # piece is not an error worth stopping for, but it must not reach
            # the exporter, which cannot write a zero-pixel image.
            continue
        out.append(
            Segment(image=piece, band=band, chunk=i, of=len(pieces), dpi=dpi)
        )
    return out


def _clear_of_markings(
    pieces: list[tuple[int, int]], band_image: np.ndarray,
    top_row: int, bottom_row: int, space: float,
    threshold: int = 160, reach_spaces: float = 4.0,
) -> list[tuple[int, int]]:
    """Move a cut off anything printed above or below the staff.

    A cut lands on a barline, which is right for the music and wrong for
    everything written *over* the barline: a rehearsal box sits centred on it,
    so a part cut there gets half a box at the end of one line and half at the
    start of the next.  The same goes for a tempo word or a hairpin that begins
    at a bar.

    The staff itself has to be ignored — the barline crosses it, that is what
    makes it a barline — so only the rows outside the staff are looked at, and
    the cut walks left until they are clear.  A few staff spaces at most: past
    that the marking is not straddling the cut, it is simply a busy page, and
    moving further would start slicing the bar instead.
    """
    if not pieces or space <= 0:
        return pieces
    top = max(0, int(top_row - reach_spaces * space))
    bottom = min(band_image.shape[0], int(bottom_row + reach_spaces * space) + 1)
    above = band_image[top : max(top + 1, int(top_row) - 1)] < threshold
    below = band_image[min(bottom - 1, int(bottom_row) + 2) : bottom] < threshold
    if not above.size and not below.size:
        return pieces
    inked = np.zeros(band_image.shape[1], dtype=bool)
    if above.size:
        inked[: above.shape[1]] |= above.any(axis=0)
    if below.size:
        inked[: below.shape[1]] |= below.any(axis=0)

    limit = max(1, int(round(3.5 * space)))
    moved: list[tuple[int, int]] = []
    previous = pieces[0][0]
    for index, (start, end) in enumerate(pieces):
        finish = end
        if index < len(pieces) - 1 and 0 <= end < inked.size and inked[end]:
            step = 0
            while step < limit and end - step - 1 > previous and inked[end - step - 1]:
                step += 1
            if step < limit:
                finish = end - step
        moved.append((previous, finish))
        previous = finish
    return [(a, b) for a, b in moved if b > a]
