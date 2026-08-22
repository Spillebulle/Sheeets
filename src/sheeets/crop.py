"""Turning a chosen staff into a rectangle on the page.

The band has to hold more than the five lines.  A part is unplayable without the
things printed around the staff: the dynamic under it, the trill line over it,
and — on a percussion staff especially — the words that say which instrument to
pick up ("S.Dr.", "B.Dr.", "to Tamb.").

A fixed amount of padding cannot do this.  Too little clips the text in half;
too much reaches into the neighbouring instrument, or picks up the copyright
line at the foot of the page.  So the band *grows*: it walks outwards from the
staff, taking whatever ink it finds, and stops at the first clear run — a gap of
about one staff space with nothing in it, which is what separates one
instrument's markings from the next.  It is capped at the midpoint to the
neighbouring staff, because ink beyond that belongs to them.
"""

from __future__ import annotations

import numpy as np

from .model import Band, DetectedPage, System


def gutter_edges(
    image: np.ndarray, y0: int, y1: int, threshold: int = 160, search_frac: float = 0.12
) -> tuple[int, int]:
    """Where the scan's binding shadow ends on the left and starts on the right.

    A spiral-bound score scanned flat leaves a black band down one edge — the
    holes and the shadow between them — and which edge it is alternates with the
    page.  It is the only thing on the page that is dark for its whole height,
    so a column-ink test finds it and nothing else.
    """
    strip = image[y0:y1, :] < threshold
    if strip.size == 0:
        return 0, image.shape[1]
    fraction = strip.mean(axis=0)
    width = image.shape[1]
    limit = int(search_frac * width)
    gap = 20  # a run of clear columns this long means the shadow has ended

    def edge(order) -> int:
        run = 0
        end = 0
        for n, x in enumerate(order):
            if fraction[x] > 0.5:
                run = 0
                end = n + 1
            else:
                run += 1
                if run >= gap:
                    break
        return end

    # The shadow has to be *joined to the edge*.  Taking the last dark column
    # anywhere in the search window instead swallowed the opening double
    # barline, which is full-height ink 180 px in, and with it the instrument
    # label sitting between the two.
    left = edge(range(limit))
    right_steps = edge(range(width - 1, width - limit - 1, -1))
    return left, width - right_steps


def ink_strip(image: np.ndarray, x0: int, x1: int, threshold: int = 160) -> np.ndarray:
    """The ink of the music columns only, as a boolean image.

    The label column and the binding shadow are left out on purpose: both are
    dark for the whole height of the page and would make every row look busy.
    """
    return image[:, max(0, x0) : max(x0 + 1, x1)] < threshold


def longest_run(row: np.ndarray, gap: int = 12) -> int:
    """The longest stretch of ink in a row, letting small gaps through.

    A line of *text* reads as one long stretch — the letters of "© Copyright
    2005 by OBRASSO-VERLAG AG" are 5 px apart.  A musical marking does not:
    "mf + B.Dr." is 105 px end to end, where the copyright line measures 144 to
    186 px per row on the same page.  That gap between them is what tells the
    page's furniture from the staff's own markings, and it is the only thing
    that does — they are the same distance below the staff and there is not one
    clear row between them.
    """
    idx = np.nonzero(row)[0]
    if idx.size == 0:
        return 0
    breaks = np.nonzero(np.diff(idx) > gap)[0]
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    return int((ends - starts).max()) + 1


def grow(
    strip: np.ndarray,
    from_row: int,
    direction: int,
    limit: float,
    space: float,
    minimum: float,
    noise: int = 6,
    text_guard_spaces: float = 3.5,
    text_run_spaces: float = 12.0,
) -> float:
    """Walk away from the staff, take everything, then give back the furniture.

    "Everything" is bounded by `limit`, which is the midpoint to the
    neighbouring staff — ink past that belongs to them, and no cleverness is
    needed to decide it.  What does need deciding is the outermost staff, where
    the limit is the edge of the page and the ink out there is a mixture: the
    part's own markings ("mf + B.Dr.", "S.Dr.") and the page's furniture (the
    copyright line, a footnote).

    They are told apart by how they are set, not by where they are — on page 3
    of the score this was written against there is not one clear row between
    them.  A line of text is a long unbroken stretch of ink: the copyright
    measures 186 px per row, where "mf + B.Dr." measures 105.  The test is made
    on a whole *block* of rows rather than on each row, because the top rows of
    a text line — where only the tall letters reach — are as sparse as any
    marking, and judged row by row they slip through and leave the tops of the
    letters sliced along the bottom of the part.
    """
    limit = max(limit, minimum)
    steps = int(round(limit))

    runs: dict[int, int] = {}
    for step in range(1, steps + 1):
        y = from_row + direction * step
        if y < 0 or y >= strip.shape[0]:
            break
        row = strip[y]
        runs[step] = longest_run(row) if row.sum() > noise else -1

    inked = [step for step, run in runs.items() if run >= 0]
    reach = max(inked) if inked else 0

    guard = int(round(text_guard_spaces * space))
    text_run = text_run_spaces * space
    gap_allowed = max(2, int(round(0.75 * space)))
    step = guard + 1
    while step <= reach:
        if runs.get(step, -1) < 0:
            step += 1
            continue
        block_start, block_end, gap, probe = step, step, 0, step
        while probe <= reach:
            if runs.get(probe, -1) >= 0:
                block_end, gap = probe, 0
            else:
                gap += 1
                if gap >= gap_allowed:
                    break
            probe += 1
        widest = max(runs.get(k, -1) for k in range(block_start, block_end + 1))
        if widest > text_run:
            # Stop short of the block; the usual margin would reach into it.
            return float(min(limit, max(minimum, block_start - 1)))
        step = block_end + 1

    # A little air after the last ink, so a descender is not shaved.
    return float(min(limit, max(minimum, reach + 0.5 * space)))


def band_for(
    page: DetectedPage,
    system: System,
    staff_indices: list[int],
    pad_spaces: float = 2.0,
    max_pad_spaces: float = 10.0,
    edge_pad_spaces: float = 6.0,
    label_spaces: float = 16.0,
    include_label: bool = True,
    right_spaces: float = 1.0,
) -> Band | None:
    if not staff_indices:
        return None
    staves = system.staves
    lo, hi = min(staff_indices), max(staff_indices)
    top_staff, bottom_staff = staves[lo], staves[hi]
    space = top_staff.space or page.space

    height, width = page.image.shape
    music_x0 = int(min(s.x0 for s in (top_staff, bottom_staff)))
    music_x1 = int(max(s.x1 for s in (top_staff, bottom_staff)))

    # Between two staves the midpoint decides; past the outermost staff there is
    # no neighbour to stop at, and what lies out there is page furniture — the
    # copyright line, the page number, a footnote.  Measured on this score the
    # markings that belong to the bottom staff ("ff", "S.Dr.") end 2 to 3 spaces
    # below it and the copyright line starts at 5, with no clear row between the
    # two, so the growth has to be capped rather than reasoned about.
    limit_up = (max_pad_spaces if lo > 0 else edge_pad_spaces) * space
    if lo > 0:
        limit_up = min(limit_up, (top_staff.top - staves[lo - 1].bottom) * 0.5)
    limit_down = (max_pad_spaces if hi + 1 < len(staves) else edge_pad_spaces) * space
    if hi + 1 < len(staves):
        limit_down = min(limit_down, (staves[hi + 1].top - bottom_staff.bottom) * 0.5)

    strip = ink_strip(page.image, music_x0, music_x1)
    pad_up = grow(strip, int(top_staff.top), -1, limit_up,
                  space=space, minimum=pad_spaces * space)
    pad_down = grow(strip, int(bottom_staff.bottom), +1, limit_down,
                    space=space, minimum=pad_spaces * space)

    y0 = int(max(0, round(top_staff.top - pad_up)))
    y1 = int(min(height, round(bottom_staff.bottom + pad_down)))
    gutter_left, gutter_right = gutter_edges(page.image, y0, y1)
    x0 = music_x0 - (label_spaces * space if include_label else 0)
    x0 = int(max(0, gutter_left, round(x0)))
    x1 = int(min(width, gutter_right, round(music_x1 + right_spaces * space)))

    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return Band(
        page_index=page.page.index,
        system_index=system.index,
        staff_index=lo,
        x0=x0, y0=y0, x1=x1, y1=y1,
        space=space,
        music_x0=music_x0,
    )


def staff_rows(page: DetectedPage, system: System, band: Band) -> tuple[int, int]:
    """Where the five lines sit inside the band, in band coordinates."""
    staff = system.staves[band.staff_index]
    return int(round(staff.top - band.y0)), int(round(staff.bottom - band.y0))


def cut(page: DetectedPage, band: Band):
    return page.image[band.y0 : band.y1, band.x0 : band.x1]
