"""Grouping staves into systems.

A full score usually prints one system per page, and a part or a piano score
prints several.  Both are the same question: is the gap to the next staff a
normal within-system gap, or the bigger one that separates systems?

The test is relative, not absolute: take the median gap between staves on the
page and call anything meaningfully larger a break.  A score with wide gaps
between instrument families (this score has three) must not be cut at those, so
the factor defaults to 2.0 — families sit about 1.15x the normal gap apart,
systems about 3x.
"""

from __future__ import annotations

import numpy as np

from .model import Staff, System


def group_systems(
    staves: list[Staff], space: float, page_index: int, factor: float = 2.0
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
    for gap, staff in zip(gaps, staves[1:]):
        if gap > threshold:
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
