"""Find staves by looking for long thin horizontal ink.

The method, and why each step is there — all of it measured on a 300 dpi scan of
a 19-stave brass band score (see NOTES.md):

1.  Threshold, then keep only pixels that sit in a horizontal run at least a few
    percent of the page wide.  That erases note heads, stems, beams and barlines
    and leaves staff lines, hairpins and the odd long slur.
2.  Label what is left and keep components that are wide (a staff line runs most
    of the system) and *thin* — thin measured as area/width, not as bounding-box
    height.  Bounding-box height is wrong: on a page scanned 0.57 degrees out of
    true a staff line's box is 35 px tall while the line is 2 px thick, and a
    height filter throws the whole page away.  That bug cost two pages out of 27
    before the ratio replaced it.
3.  Fit a straight line to each component and take the median slope as the
    page's skew.  Rotate the image flat, then detect again on the rotated image
    so every later stage can treat a staff as a rectangle.  The rotation
    direction is *checked* rather than assumed: rotate, re-measure the slope,
    and if it got worse, go the other way.  (It did get worse the first time —
    the sign convention between "slope in image coordinates" and PIL's
    counter-clockwise rotate is easy to get backwards, and with the wrong sign
    the skew doubles instead of cancelling.)
4.  Merge fragments — a staff line broken in half by heavy ink shows up as two
    components at the same height — then group lines into fives by looking for
    four more lines at multiples of the spacing.  Grouping by "five in a row
    that are evenly spaced" fails, because one spurious line between two staves
    breaks the run; searching for the pattern instead does not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..layout import group_systems
from ..model import DetectedPage, PageImage, Staff
from . import register


def binarise(arr: np.ndarray, threshold: int | None = None) -> np.ndarray:
    """Ink mask.  A fixed threshold is fine for print; Otsu when asked."""
    if threshold is None:
        threshold = otsu(arr)
    return arr < threshold


def binarise_local(arr: np.ndarray, window: int = 61, drop: int = 18) -> np.ndarray:
    """Ink mask against the local background rather than one level for the page.

    Needed where the printing is uneven: on the crooked part in the fleet the
    first three systems are set in much lighter ink than the rest, and a single
    threshold that keeps their staff lines drowns the dense systems below in
    black.  Comparing each pixel with the average around it sees both.

    It is not a free win — on a *photograph*, where the background itself
    varies (a table, a shadow, a curled page), a wide window smears across the
    edge of the paper and the same trick loses almost everything.  Which is why
    the detector tries this and a plain threshold and keeps whichever finds
    more staves, rather than choosing for the page in advance.
    """
    from scipy import ndimage

    background = ndimage.uniform_filter(arr.astype(np.float32), size=window)
    return arr < (background - drop)


def ink_strategies(threshold: int | None) -> list[tuple[str, object]]:
    """The ways of deciding what is ink, in the order they are tried."""
    return [
        (f"fixed {threshold}", lambda a: binarise(a, threshold)),
        ("otsu", lambda a: binarise(a, None)),
        ("local 61", lambda a: binarise_local(a, 61, 18)),
        ("local 121", lambda a: binarise_local(a, 121, 15)),
    ]


def otsu(arr: np.ndarray) -> int:
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = (mu_t * omega - mu) ** 2 / denom
    sigma_b[~np.isfinite(sigma_b)] = 0
    # Between two clean tones every level between them separates equally well,
    # and argmax would return the darker end — which, with `ink = arr <
    # threshold`, finds no ink at all.  Take the middle of the plateau.
    best = np.flatnonzero(sigma_b >= sigma_b.max() - 1e-9)
    return int(round(float(best.mean())))


def horizontal_runs(mask: np.ndarray, min_len: int) -> np.ndarray:
    """Keep only pixels in a horizontal run of at least `min_len`.

    Vectorised: the per-row loop this replaces was the whole cost of a page.
    """
    h, w = mask.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    rs, cs = np.nonzero(diff == 1)
    re, ce = np.nonzero(diff == -1)
    # nonzero walks row by row, so the k-th start in a row meets the k-th end.
    keep = (ce - cs) >= min_len
    acc = np.zeros((h, w + 2), dtype=np.int32)
    np.add.at(acc, (rs[keep], cs[keep]), 1)
    np.add.at(acc, (re[keep], ce[keep]), -1)
    return np.cumsum(acc, axis=1)[:, :w] > 0


@dataclass
class LineCandidate:
    a: float  # y = a + b*x
    b: float
    x0: int
    x1: int
    width: int
    thickness: float

    def y_at(self, x: float) -> float:
        return self.a + self.b * x


def line_candidates(
    ink: np.ndarray,
    min_width_frac: float = 0.04,
    max_thickness: float = 6.0,
    run_frac: float = 0.03,
    drift: int = 1,
) -> list[LineCandidate]:
    """Find the long thin horizontal things on a page.

    The width floor is deliberately low.  A staff line is not always found in
    one piece: where the print has faded, one line comes back as five or six
    fragments of a tenth of the page each.  Filtering fragments by width here
    threw those lines away — and with them the two faded systems at the top of
    the crooked part — so the floor only rejects specks, and the real width
    test is applied after the fragments of a line have been put back together.

    `drift` lets a line wander vertically by that many pixels and still count
    as one run.  It matters more than it sounds: a page whose skew *varies*
    down the sheet — a sheet held slightly curved over the scanner, which is
    most old parts — cannot be straightened by one rotation, so after deskewing
    the far end of the page is still a fraction of a degree out.  At 0.5 degrees
    a line stays inside one row of pixels for barely a hundred of them, the
    run filter cuts it to pieces, and those systems vanish.  On the crooked
    part in the fleet the top two systems of thirteen were lost exactly so.

    Dilating by a pixel before the filter and masking back afterwards keeps the
    measured thickness honest while letting a drifting line survive.
    """
    from scipy import ndimage

    h, w = ink.shape
    searched = ink
    if drift:
        searched = ink.copy()
        for shift in range(1, drift + 1):
            searched[:-shift] |= ink[shift:]
            searched[shift:] |= ink[:-shift]
    runs = horizontal_runs(searched, max(8, int(run_frac * w))) & ink
    labels, _ = ndimage.label(runs, structure=np.ones((3, 3), dtype=int))
    out: list[LineCandidate] = []
    for k, slc in enumerate(ndimage.find_objects(labels), start=1):
        if slc is None:
            continue
        ys, xs = slc
        width = xs.stop - xs.start
        if width < min_width_frac * w:
            continue
        sub = labels[slc] == k
        area = int(sub.sum())
        if area / width > max_thickness:
            continue
        rows = np.arange(ys.start, ys.stop)[:, None]
        mass = sub.sum(0)
        cols = np.nonzero(mass)[0]
        centres = (sub * rows).sum(0)[cols] / mass[cols]
        x = cols + xs.start
        b, a = np.polyfit(x, centres, 1)
        out.append(
            LineCandidate(
                a=float(a), b=float(b), x0=int(x.min()), x1=int(x.max()),
                width=int(width), thickness=area / width,
            )
        )
    return out


def rotate(arr: np.ndarray, degrees: float) -> np.ndarray:
    if abs(degrees) < 0.01:
        return arr
    from PIL import Image

    return np.asarray(
        Image.fromarray(arr).rotate(degrees, resample=Image.BICUBIC, fillcolor=255)
    )


def merge_fragments(
    cands: list[LineCandidate], x_ref: float, tolerance: float
) -> list[tuple[float, int]]:
    """Collapse candidates that describe the same line.  Returns (y, width)."""
    ordered = sorted(cands, key=lambda c: c.y_at(x_ref))
    merged: list[list[float]] = []
    for c in ordered:
        y = c.y_at(x_ref)
        if merged and abs(y - merged[-1][0]) < tolerance:
            m = merged[-1]
            total = m[1] + c.width
            m[0] = (m[0] * m[1] + y * c.width) / total
            m[1] = total
        else:
            merged.append([y, float(c.width)])
    return [(y, int(w)) for y, w in merged]


def space_from_runs(ink: np.ndarray, sample: int = 4,
                    low: int = 3, high: int = 80) -> float | None:
    """Staff space, measured from the ink itself rather than from what was found.

    The gaps between *detected lines* are not a safe way to measure this.  On a
    photograph of an old part every staff line is found twice — the print has
    spread, and the two halves come back as separate components four pixels
    apart — so half the gaps are 4 px, the estimate collapses to 8, and the
    comb then hunts for five lines 8 px apart and finds no staff at all on the
    page.  That is exactly what happened to the worst scan in the fleet.

    Scanning down a column instead: the most common run of ink is the thickness
    of a staff line, and the most common run of white is the space between two
    of them.  A staff contributes four of each and nothing else on the page is
    as regular, so both modes are sharp.  The distance from one line to the
    next — which is what everything downstream means by "space" — is the two
    added together.
    """
    if ink.size == 0:
        return None
    columns = ink[:, ::sample].T  # one row per sampled column
    padded = np.zeros((columns.shape[0], columns.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = columns
    diff = np.diff(padded, axis=1)
    rows_start, starts = np.nonzero(diff == 1)   # ink begins
    rows_end, ends = np.nonzero(diff == -1)      # ink ends
    if starts.size < 2:
        return None

    thickness = ends - starts
    thickness = thickness[(thickness >= 1) & (thickness <= 20)]
    # Within one column, the white gap runs from the end of one ink run to the
    # start of the next; pairs that straddle two columns are dropped.
    white = starts[1:] - ends[:-1]
    same = rows_start[1:] == rows_end[:-1]
    white = white[same & (white >= low) & (white <= high)]
    if white.size < 20 or thickness.size < 20:
        return None
    return float(np.argmax(np.bincount(white)) + np.argmax(np.bincount(thickness)))


def estimate_space(ys: list[float]) -> float | None:
    """Distance between adjacent staff lines, from the gaps between candidates."""
    gaps = np.diff(sorted(ys))
    gaps = gaps[(gaps > 2)]
    if gaps.size < 4:
        return None
    # Inside a staff there are four gaps per staff and one bigger gap between
    # staves, so the small gaps dominate; the median of the lower half is the
    # spacing even when a few lines are missing.
    small = gaps[gaps <= np.percentile(gaps, 60)]
    return float(np.median(small)) if small.size else float(np.median(gaps))


def comb_staves(
    ys: list[float],
    space: float,
    tolerance: float = 0.40,
    min_lines: int = 4,
) -> list[list[float]]:
    """Pick out staves: five lines a `space` apart, allowing for a bad scan.

    Two things go wrong on real paper and both have to be tolerated, or the
    good pages work and the poor ones return nothing at all:

    * **The lines wobble.**  On a photographed part the detected positions of
      one staff's lines came out 18, 15, 21, 17 apart where the spacing is 18.
      Demanding exact multiples finds no staff.
    * **A line goes missing.**  Faint print, a fold, a stave crossed by a slur:
      four of the five are found and the fifth is not.  A staff with four lines
      is still a staff, so four is enough to claim one — and the fifth is then
      *computed* from the four rather than left out, because everything
      downstream measures the band from the outer lines.

    Accepting four lines could invent a staff out of unrelated ink, so the
    lines that are found must also *fit*: a straight line through them, index
    against position, with residuals inside a quarter of a space.
    """
    ys = sorted(ys)
    used = [False] * len(ys)
    staves: list[list[float]] = []

    for i, y0 in enumerate(ys):
        if used[i]:
            continue
        chosen = {0: i}
        for k in range(1, 5):
            target = y0 + k * space
            best, best_distance = None, tolerance * space
            for j, y in enumerate(ys):
                if used[j] or j in chosen.values():
                    continue
                distance = abs(y - target)
                if distance < best_distance:
                    best, best_distance = j, distance
            if best is not None:
                chosen[k] = best
        if len(chosen) < min_lines:
            continue

        # A straight line through the ones that were found; it both checks the
        # fit and supplies whichever line is missing.
        indices = sorted(chosen)
        positions = [ys[chosen[k]] for k in indices]
        slope, intercept = np.polyfit(indices, positions, 1)
        fitted = [slope * k + intercept for k in range(5)]
        residual = max(abs(ys[chosen[k]] - fitted[k]) for k in indices)
        if residual > 0.25 * space or not (0.75 * space <= slope <= 1.25 * space):
            continue

        for j in chosen.values():
            used[j] = True
        staves.append(fitted)

    return staves


class ProjectionDetector:
    """The shipped detector.  Every threshold is a keyword so a hard scan can be
    talked round without editing the module."""

    def __init__(
        self,
        threshold: int | None = 160,
        min_width_frac: float = 0.20,
        fragment_frac: float = 0.04,
        max_thickness: float = 6.0,
        run_frac: float = 0.03,
        deskew: bool = True,
        system_gap_factor: float = 2.0,
        try_harder: bool = True,
    ) -> None:
        self.threshold = threshold
        self.min_width_frac = min_width_frac
        self.fragment_frac = fragment_frac
        self.max_thickness = max_thickness
        self.run_frac = run_frac
        self.deskew = deskew
        self.system_gap_factor = system_gap_factor
        self.try_harder = try_harder

    # -- internals ---------------------------------------------------------
    def _candidates(self, arr: np.ndarray, ink=None) -> list[LineCandidate]:
        return line_candidates(
            binarise(arr, self.threshold) if ink is None else ink(arr),
            min_width_frac=self.fragment_frac,
            max_thickness=self.max_thickness,
            run_frac=self.run_frac,
        )

    def _flatten(self, arr: np.ndarray, ink=None) -> tuple[np.ndarray, list[LineCandidate], float]:
        cands = self._candidates(arr, ink)
        if not cands or not self.deskew:
            return arr, cands, 0.0
        slope = float(np.median([c.b for c in cands]))
        degrees = math.degrees(math.atan(slope))
        if abs(degrees) < 0.02:
            return arr, cands, 0.0
        best = (arr, cands, 0.0, abs(slope))
        for sign in (1, -1):
            turned = rotate(arr, sign * degrees)
            turned_cands = self._candidates(turned, ink)
            if not turned_cands:
                continue
            residual = abs(float(np.median([c.b for c in turned_cands])))
            if residual < best[3]:
                best = (turned, turned_cands, sign * degrees, residual)
            if residual < 0.2 * abs(slope):
                # Flat enough that the other direction cannot win; skip it
                # rather than detect the page a third time.
                break
        return best[0], best[1], best[2]

    # -- the contract ------------------------------------------------------
    def detect(self, page: PageImage) -> DetectedPage:
        """Find the staves, trying more than one idea of what counts as ink.

        Strategies are tried in turn and the best answer wins — most staves,
        ties to the most regular page.  The search stops early only when the
        answer looks *complete*, which is a stricter question than whether it
        looks reasonable: on the crooked part the plain threshold finds eleven
        evenly spaced staves and looks entirely healthy, but the page has
        thirteen and the two it drops are the ones printed in lighter ink.
        Evenly spaced is not the same as complete — what tells them apart is
        whether the staves account for the ink that is on the page.
        """
        attempts: list[tuple[int, bool, DetectedPage, str]] = []
        for name, ink in ink_strategies(self.threshold):
            result = self._detect_with(page, ink, name)
            attempts.append((len(result.staves), _looks_regular(result), result, name))
            if not self.try_harder or _looks_complete(result, page.array):
                break
        if not attempts:  # pragma: no cover - ink_strategies is never empty
            return DetectedPage(page=page, image=page.array, systems=[], space=0.0,
                                skew_deg=0.0, notes={"reason": "nothing tried"})
        count, _regular, result, name = max(attempts, key=lambda a: (a[0], a[1]))
        result.notes["ink"] = name
        result.notes["ink_tried"] = [a[3] for a in attempts]
        return result

    def _detect_with(self, page: PageImage, ink, name: str) -> DetectedPage:
        image, cands, skew = self._flatten(page.array, ink)
        if not cands:
            return DetectedPage(page=page, image=image, systems=[], space=0.0, skew_deg=skew,
                                notes={"reason": "no line-shaped ink found"})
        x_ref = image.shape[1] / 2
        rough = [c.y_at(x_ref) for c in cands]
        # Measured off the ink first; the gaps between detected lines are only
        # a fallback, because a line found twice halves that estimate.
        space = space_from_runs(ink(image))
        if space is None or space < 3:
            space = estimate_space(rough)
        if space is None:
            return DetectedPage(page=page, image=image, systems=[], space=0.0, skew_deg=skew,
                                notes={"reason": "could not estimate staff spacing"})
        merged = merge_fragments(cands, x_ref, tolerance=0.45 * space)
        # Now that the pieces of each line are back together, ask how wide the
        # line really is.  A staff line runs most of the way across; a slur or
        # a beam does not.
        wide = [(y, w) for y, w in merged if w >= self.min_width_frac * image.shape[1]]
        groups = comb_staves([y for y, _ in wide], space)
        groups = recover_gaps(groups, [y for y, _ in wide], space)
        staves = [
            Staff(lines=g, space=float(np.median(np.diff(g))),
                  **_extent(g, cands, x_ref, space, image.shape[1]))
            for g in groups
        ]
        systems = group_systems(staves, space, page.index,
                                factor=self.system_gap_factor, image=image)
        return DetectedPage(
            page=page,
            image=image,
            systems=systems,
            space=space,
            skew_deg=skew,
            notes={"line_candidates": len(cands), "merged_lines": len(merged),
                   "wide_lines": len(wide)},
        )


def recover_gaps(
    groups: list[list[float]], ys: list[float], space: float,
    tolerance: float = 0.18, min_lines: int = 3,
) -> list[list[float]]:
    """Look again where the layout says a staff should be.

    Music is laid out on a grid, so a gap of exactly two staves' spacing in an
    otherwise even column of staves is not a wide margin — it is a staff that
    was not found.  Knowing *where* to look is what makes it safe to look with
    weaker evidence: three lines instead of four, which would invent staves all
    over the page if applied everywhere.

    On the three-player page this recovers the glockenspiel staff, whose middle
    lines are buried under beamed semiquavers.
    """
    if len(groups) < 3:
        return groups
    tops = [g[0] for g in groups]
    order = sorted(range(len(groups)), key=lambda i: tops[i])
    sorted_tops = [tops[i] for i in order]
    gaps = np.diff(sorted_tops)
    if gaps.size < 2:
        return groups
    typical = float(np.median(gaps))
    if typical <= 0:
        return groups

    recovered: list[list[float]] = []
    for gap, top in zip(gaps, sorted_tops):
        if abs(gap - 2 * typical) > tolerance * 2 * typical:
            continue
        target = top + typical
        found = []
        for k in range(5):
            want = target + k * space
            near = [y for y in ys if abs(y - want) <= 0.4 * space]
            if near:
                found.append((k, min(near, key=lambda y: abs(y - want))))
        if len(found) < min_lines:
            continue
        indices = [k for k, _ in found]
        positions = [y for _, y in found]
        slope, intercept = np.polyfit(indices, positions, 1)
        if not (0.75 * space <= slope <= 1.25 * space):
            continue
        fitted = [slope * k + intercept for k in range(5)]
        if max(abs(y - fitted[k]) for k, y in found) > 0.25 * space:
            continue
        recovered.append(fitted)
    return sorted(groups + recovered, key=lambda g: g[0])


def _extent(lines: list[float], cands: list[LineCandidate], x_ref: float,
            space: float, width: int) -> dict:
    """Where this staff's own lines begin and end.

    Every staff used to be given the page's median extent, which is wrong for
    the one place it matters most: the *first* system of a score is indented to
    make room for the instrument names.  Judged against the page median, the
    barline joining its staves is outside the window that looks for it, so the
    first system of a three-player page came back as three separate systems
    while every later page was read correctly.
    """
    mine = [
        c for c in cands
        if min(abs(c.y_at(x_ref) - line) for line in lines) <= 0.4 * space
    ]
    if not mine:
        return {"x0": 0, "x1": width}
    return {"x0": int(np.median([c.x0 for c in mine])),
            "x1": int(np.median([c.x1 for c in mine]))}


def _looks_complete(result: DetectedPage, original: np.ndarray,
                    coverage: float = 0.8) -> bool:
    """Do the staves account for the ink on the page?

    The cheap test for "no need to try another way of reading this".  Staves
    can be evenly spaced and still be missing two systems; what gives that away
    is a stretch of the page with ink on it and no staff in it.
    """
    staves = result.staves
    if len(staves) < 3 or not _looks_regular(result):
        return False
    ink_rows = np.nonzero((original < 160).mean(axis=1) > 0.02)[0]
    if ink_rows.size < 10:
        return False
    extent = float(ink_rows[-1] - ink_rows[0])
    if extent <= 0:
        return False
    span = max(s.bottom for s in staves) - min(s.top for s in staves)
    return bool(span >= coverage * extent)


def _looks_regular(result: DetectedPage, tolerance: float = 0.25) -> bool:
    """Do the staves sit at even intervals, as engraved music does?

    This is the test for "no need to try anything else".  Music is laid out on
    a grid; a page where the found staves are evenly spaced has almost
    certainly been read correctly, and a page where they are not has usually
    lost some.
    """
    staves = result.staves
    if len(staves) < 3:
        return False
    tops = sorted(s.top for s in staves)
    gaps = np.diff(tops)
    if gaps.size == 0:
        return False
    typical = float(np.median(gaps))
    if typical <= 0:
        return False
    return bool(np.all(np.abs(gaps - typical) <= tolerance * typical))


register("projection", ProjectionDetector)
