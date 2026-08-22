"""Grouping staves into systems.

A full score prints one system of many staves; a part prints many systems of
one.  Telling them apart by the size of the gaps does not work, and the fleet
showed why: on a part page every gap is the same size, so "a gap much bigger
than the median" never fires and eight separate systems are read as one system
of eight staves.  On this repository's test fleet that mis-read both parts and
neither score.

What actually separates them is ink.  A system is *joined*: the barline at its
left edge runs from the top staff to the bottom one, which is what makes it a
system rather than staves that happen to be near each other.  Two staves in a
part are not joined by anything.  So the question "same system?" is asked of
the page — is there a column of ink bridging the gap? — and the gap sizes are
only a fallback for when there is no image to look at.
"""

from __future__ import annotations

import numpy as np

from .model import Staff, System


def joined(image, upper: Staff, lower: Staff, threshold: int = 160,
           reach_spaces: float = 3.0, min_columns: int = 1) -> bool:
    """Is there a barline bridging the gap between these two staves?"""
    if image is None:
        return False
    top = int(round(upper.bottom))
    bottom = int(round(lower.top))
    if bottom - top < 3:
        return True
    space = upper.space or lower.space or 10.0
    # The joining barline is at the left edge of the system, where the bracket
    # is; look there and a little to the right of it.
    x0 = max(0, int(upper.x0 - space))
    x1 = min(image.shape[1], int(upper.x0 + reach_spaces * space))
    if x1 - x0 < 2:
        return False
    gap = image[top + 1 : bottom, x0:x1] < threshold
    if gap.size == 0:
        return True
    return int((gap.mean(axis=0) > 0.9).sum()) >= min_columns


def group_systems(
    staves: list[Staff], space: float, page_index: int, factor: float = 2.0,
    image=None,
) -> list[System]:
    if not staves:
        return []
    staves = sorted(staves, key=lambda s: s.top)
    if len(staves) == 1:
        staves[0].index = 0
        return [System(staves=list(staves), page_index=page_index, index=0)]

    gaps = np.array([b.top - a.bottom for a, b in zip(staves, staves[1:])], dtype=float)
    typical = float(np.median(gaps))
    threshold = max(typical * factor, space * 6.0)

    systems: list[System] = []
    current: list[Staff] = [staves[0]]
    for gap, upper, staff in zip(gaps, staves, staves[1:]):
        if image is not None:
            starts_new = not joined(image, upper, staff)
        else:
            starts_new = gap > threshold
        if starts_new:
            systems.append(System(staves=current, page_index=page_index, index=len(systems)))
            current = [staff]
        else:
            current.append(staff)
    systems.append(System(staves=current, page_index=page_index, index=len(systems)))

    for system in systems:
        for i, staff in enumerate(system.staves):
            staff.index = i
    return systems


def staff_counts(systems: list[System]) -> list[int]:
    return [len(s) for s in systems]
