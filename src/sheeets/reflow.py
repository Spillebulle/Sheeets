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

    needed = max(2, int(round(support * len(system.staves))))
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
    out: list[Segment] = []
    for i, (a, b) in enumerate(pieces):
        # Only the first piece can carry the instrument label; a continuation
        # starts inside the music and has none to drop.
        left = a
        if i == 0 and not keep_label_on_first:
            left = max(a, label_width)
        out.append(
            Segment(
                image=band_image[:, left:b],
                band=band,
                chunk=i,
                of=len(pieces),
                dpi=dpi,
            )
        )
    return out
