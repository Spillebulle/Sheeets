"""Turning a chosen staff into a rectangle on the page.

The band has to hold more than the five lines: ledger lines, the dynamic under
the staff, the "S.Dr." above the first note, a trill line over the top.  It also
has to stop before it eats the neighbouring instrument, so the padding is capped
at half the distance to the next staff.  Where there is no neighbour — the top
and bottom of the page — the cap is the page edge instead, which is why the
bottom staff of a score can pick up the copyright line if `pad` is generous.
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


def band_for(
    page: DetectedPage,
    system: System,
    staff_indices: list[int],
    pad_spaces: float = 3.5,
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

    pad_up = pad_spaces * space
    if lo > 0:
        pad_up = min(pad_up, (top_staff.top - staves[lo - 1].bottom) * 0.5)
    pad_down = pad_spaces * space
    if hi + 1 < len(staves):
        pad_down = min(pad_down, (staves[hi + 1].top - bottom_staff.bottom) * 0.5)

    height, width = page.image.shape
    y0 = int(max(0, round(top_staff.top - pad_up)))
    y1 = int(min(height, round(bottom_staff.bottom + pad_down)))

    music_x0 = int(min(s.x0 for s in (top_staff, bottom_staff)))
    music_x1 = int(max(s.x1 for s in (top_staff, bottom_staff)))
    gutter_left, gutter_right = gutter_edges(page.image, y0, y1)
    x0 = music_x0 - (label_spaces * space if include_label else 0)
    x0 = int(max(0, gutter_left, round(x0)))
    x1 = int(min(width, gutter_right, round(music_x1 + right_spaces * space)))

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
