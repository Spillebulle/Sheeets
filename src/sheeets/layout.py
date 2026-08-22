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
           min_columns: int = 1) -> bool:
    """Is there a barline running through both staves and the gap between?

    Three versions of this were wrong before this one, each in an instructive
    way.  Looking at the *left edge* alone depends on knowing exactly where the
    staff starts, and a staff line detected a little short splits a
    nineteen-stave system in two.  Looking across the whole width but only at
    the *gap* is worse on hand-copied manuscript, where a stray stroke between
    two systems joins them and a whole page collapses into one system.

    What a system barline does that neither of those catches is run the full
    height — through the upper staff, through the gap, and through the lower
    one.  Nothing in a part does that, because a part's barlines stop at their
    own staff.
    """
    if image is None:
        return False
    top = int(round(upper.top))
    bottom = int(round(lower.bottom))
    if bottom - top < 6:
        return True
    # Only where the music is.  A scan often has a dark border down one edge —
    # on the hand-copied part in the fleet it is 65 columns wide — and it runs
    # the height of the page, so it "joins" every staff to every other and the
    # whole sheet collapses into one system.
    space = upper.space or lower.space or 10.0
    left = max(0, int(min(upper.x0, lower.x0) - space))
    right = min(image.shape[1], int(max(upper.x1, lower.x1) + space))
    if right - left < 4:
        return False
    span = image[top:bottom, left:right] < threshold
    if span.size == 0:
        return True
    return int((span.mean(axis=0) > 0.9).sum()) >= min_columns


def group_systems(
    staves: list[Staff], space: float, page_index: int, factor: float = 2.0,
    image=None,
) -> list[System]:
    """Group staves into systems.

    Three signals, and only together do they work:

    * **Ink.**  A system is joined by barlines running through its staves.
      This is what tells a part (nothing joins anything) from a score.
    * **Equal groups.**  Systems on a page carry the same instruments, so they
      hold the same number of staves.  This is what rescues a score that
      *breaks* its barlines between instrument families — this one does,
      between the basses and the percussion — where the ink alone splits a
      19-stave system into 14 and 5.  Unequal groups mean the split is wrong.
    * **Gap size**, only as a fallback when there is no image to look at.

    Gap size cannot do the job itself and the fleet shows why twice over: on a
    part every gap is identical, and on the three-player page the gap between
    systems (134 px) is the same as the gap inside one (133 px).  There the ink
    is the only evidence there is.
    """
    if not staves:
        return []
    staves = sorted(staves, key=lambda s: s.top)
    if len(staves) == 1:
        staves[0].index = 0
        return [System(staves=list(staves), page_index=page_index, index=0)]

    gaps = [b.top - a.bottom for a, b in zip(staves, staves[1:])]
    typical = float(np.median(gaps))
    threshold = max(typical * factor, space * 6.0)

    if image is None:
        breaks = [gap > threshold for gap in gaps]
    else:
        breaks = [not joined(image, upper, lower)
                  for upper, lower in zip(staves, staves[1:])]
        if all(breaks):
            pass  # a part: every staff stands alone
        elif not _groups_are_even(breaks):
            # The ink says split, but into groups of different sizes — which
            # systems on one page never are.  Try to regularise it first: one
            # page of the three-player set came back [3, 1, 1, 1, 3, 3, 3]
            # because one system's inner barlines were too faint to find, and
            # those three singletons plainly make up the missing three.
            repaired = _regularise(breaks)
            breaks = repaired if repaired is not None else [g > threshold for g in gaps]

    systems: list[System] = []
    current: list[Staff] = [staves[0]]
    for index, starts_new in enumerate(breaks):
        if starts_new:
            systems.append(System(staves=current, page_index=page_index, index=len(systems)))
            current = [staves[index + 1]]
        else:
            current.append(staves[index + 1])
    systems.append(System(staves=current, page_index=page_index, index=len(systems)))

    for system in systems:
        for i, staff in enumerate(system.staves):
            staff.index = i
    return systems


def _sizes(breaks: list[bool]) -> list[int]:
    sizes: list[int] = []
    run = 1
    for starts_new in breaks:
        if starts_new:
            sizes.append(run)
            run = 1
        else:
            run += 1
    sizes.append(run)
    return sizes


def _regularise(breaks: list[bool]) -> list[bool] | None:
    """Make uneven groups even, if the sizes say plainly how.

    Systems on a page hold the same number of staves, so the commonest group
    size is what a system is.  A run of smaller groups adding up to exactly
    that is one system whose inner barlines were missed, and merging them is
    safe.  Anything that does not come out even is left alone — a page that
    cannot be regularised is not one to guess at.
    """
    sizes = _sizes(breaks)
    if len(sizes) < 3:
        return None
    from collections import Counter

    modal, times = Counter(sizes).most_common(1)[0]
    if times < 2 or modal < 1:
        return None

    merged: list[int] = []
    run = 0
    for size in sizes:
        if size > modal:
            return None
        run += size
        if run == modal:
            merged.append(run)
            run = 0
        elif run > modal:
            return None
    if run:
        return None
    if len(set(merged)) != 1:
        return None

    out: list[bool] = []
    for n, size in enumerate(merged):
        out.extend([False] * (size - 1))
        if n + 1 < len(merged):
            out.append(True)
    return out if len(out) == len(breaks) else None


def _groups_are_even(breaks: list[bool]) -> bool:
    """Would splitting here give systems of the same size?"""
    sizes: list[int] = []
    run = 1
    for starts_new in breaks:
        if starts_new:
            sizes.append(run)
            run = 1
        else:
            run += 1
    sizes.append(run)
    if len(sizes) < 2:
        return True
    return max(sizes) == min(sizes)


def staff_counts(systems: list[System]) -> list[int]:
    return [len(s) for s in systems]
