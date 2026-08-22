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
    coverage: float = 0.95,
    merge_within: int = 4,
) -> list[int]:
    """Columns (band coordinates) where a barline crosses the staff."""
    top_row = max(0, top_row)
    bottom_row = min(band_image.shape[0] - 1, bottom_row)
    if bottom_row - top_row < 4:
        return []
    ink = band_image[top_row : bottom_row + 1] < threshold
    fraction = ink.mean(axis=0)
    touches_ends = ink[:2].any(axis=0) & ink[-2:].any(axis=0)
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


def cut_points(
    width: int,
    max_width: int,
    barline_cols: list[int],
    start: int = 0,
    snap: float = 0.35,
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
    count = int(-(-span // max_width))  # ceil
    ideal = span / count
    pieces: list[tuple[int, int]] = []
    x = start
    for k in range(1, count):
        target = start + ideal * k
        window = snap * ideal
        candidates = [b for b in barline_cols if x < b <= min(x + max_width, target + window)
                      and abs(b - target) <= window]
        cut = int(min(candidates, key=lambda b: abs(b - target))) if candidates else int(target)
        if cut <= x:
            continue
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
) -> list[Segment]:
    """Cut one band into the pieces that will be drawn, in order."""
    cols = barlines(band_image, top_row, bottom_row)
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
