"""Finding the words printed around a staff — and not pretending to read them.

"S.Dr.", "+ B.Dr.", "+ C. Cym.", "solo" — a percussion part without them says
which rhythms to play and not which drum to play them on.  The extracted part
keeps them because it keeps the paper.  The retyped one cannot: measured on
this score, Audiveris's text step returned exactly one word from twenty-seven
pages of a nineteen-stave conductor's score, "Presto".

Reading them here was tried and does not work, and the measurement is worth
keeping so that nobody spends the afternoon again.  Over the whole percussion
part, with two enlargements required to agree and a filter for marking-shaped
answers, **three** of ninety-eight runs of text produced anything, and two of
those three were rubbish that slipped the filter — "Y of", "JJI" — against one
truncated "Cym".  Rendering at 600 dpi instead of 300 changed nothing: the
limit is not resolution but that these are two- and three-letter abbreviations
set among slur ends and dynamics, with no sequence, no arithmetic and no
alphabet to check an answer against.  A part that names the wrong drum is worse
than one that names none.

So this locates them and stops.  Ninety-eight positions, each mapped to a bar,
is a true and useful statement: it tells the player exactly where the fresh
part is missing something and the extracted part has it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Marking:
    """A run of text-sized ink beside the staff: where it is, not what it says."""

    x: int
    above: bool


def find(image: np.ndarray, staff, threshold: int = 160,
         reach: float = 3.4) -> list[Marking]:
    """Every run of text-sized ink in the bands either side of one staff.

    Text is told from music by size and by company: a letter is between half a
    staff space and two, and letters come in runs.  A single blob that wide
    apart from its neighbours is a dynamic or a staccato dot, and is left out —
    the engine reads dynamics well enough, and it is the words it misses.
    """
    from scipy import ndimage

    space = float(staff.space)
    if space <= 0:
        return []
    out: list[Marking] = []
    for above, y0, y1 in (
        (True, staff.top - reach * space, staff.top - 0.4 * space),
        (False, staff.bottom + 0.5 * space, staff.bottom + reach * space),
    ):
        top, bottom = max(0, int(y0)), min(image.shape[0], int(y1))
        if bottom - top < 4:
            continue
        labels, _ = ndimage.label(image[top:bottom] < threshold,
                                  structure=np.ones((3, 3), dtype=int))
        pieces = []
        for slices in ndimage.find_objects(labels):
            if slices is None:
                continue
            ys, xs = slices
            height, width = ys.stop - ys.start, xs.stop - xs.start
            if 0.45 * space <= height <= 2.2 * space and 0.1 * space <= width <= 3.0 * space:
                pieces.append((int(xs.start), int(xs.stop)))
        if not pieces:
            continue
        pieces.sort()
        runs = [list(pieces[0])]
        for x0, x1 in pieces[1:]:
            if x0 - runs[-1][1] <= 1.1 * space:      # one phrase, not one letter
                runs[-1][1] = max(runs[-1][1], x1)
            else:
                runs.append([x0, x1])
        out.extend(Marking(x0, above) for x0, x1 in runs if x1 - x0 >= 1.5 * space)
    return out
