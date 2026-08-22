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
    min_width_frac: float = 0.20,
    max_thickness: float = 6.0,
    run_frac: float = 0.03,
) -> list[LineCandidate]:
    from scipy import ndimage

    h, w = ink.shape
    runs = horizontal_runs(ink, max(8, int(run_frac * w)))
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


def comb_staves(ys: list[float], space: float, tolerance: float = 0.35) -> list[list[float]]:
    """Pick out sets of five lines at `space` apart, top-down, without reuse."""
    ys = sorted(ys)
    used = [False] * len(ys)
    staves: list[list[float]] = []
    for i, y0 in enumerate(ys):
        if used[i]:
            continue
        chosen = [i]
        for k in range(1, 5):
            target = y0 + k * space
            best, best_d = None, tolerance * space
            for j, y in enumerate(ys):
                if used[j] or j in chosen:
                    continue
                d = abs(y - target)
                if d < best_d:
                    best, best_d = j, d
            if best is None:
                break
            chosen.append(best)
        if len(chosen) == 5:
            for j in chosen:
                used[j] = True
            staves.append([ys[j] for j in chosen])
    return staves


class ProjectionDetector:
    """The shipped detector.  Every threshold is a keyword so a hard scan can be
    talked round without editing the module."""

    def __init__(
        self,
        threshold: int | None = 160,
        min_width_frac: float = 0.20,
        max_thickness: float = 6.0,
        run_frac: float = 0.03,
        deskew: bool = True,
        system_gap_factor: float = 2.0,
    ) -> None:
        self.threshold = threshold
        self.min_width_frac = min_width_frac
        self.max_thickness = max_thickness
        self.run_frac = run_frac
        self.deskew = deskew
        self.system_gap_factor = system_gap_factor

    # -- internals ---------------------------------------------------------
    def _candidates(self, arr: np.ndarray) -> list[LineCandidate]:
        return line_candidates(
            binarise(arr, self.threshold),
            min_width_frac=self.min_width_frac,
            max_thickness=self.max_thickness,
            run_frac=self.run_frac,
        )

    def _flatten(self, arr: np.ndarray) -> tuple[np.ndarray, list[LineCandidate], float]:
        cands = self._candidates(arr)
        if not cands or not self.deskew:
            return arr, cands, 0.0
        slope = float(np.median([c.b for c in cands]))
        degrees = math.degrees(math.atan(slope))
        if abs(degrees) < 0.02:
            return arr, cands, 0.0
        best = (arr, cands, 0.0, abs(slope))
        for sign in (1, -1):
            turned = rotate(arr, sign * degrees)
            turned_cands = self._candidates(turned)
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
        image, cands, skew = self._flatten(page.array)
        if not cands:
            return DetectedPage(page=page, image=image, systems=[], space=0.0, skew_deg=skew,
                                notes={"reason": "no line-shaped ink found"})
        x_ref = image.shape[1] / 2
        rough = [c.y_at(x_ref) for c in cands]
        space = estimate_space(rough)
        if space is None:
            return DetectedPage(page=page, image=image, systems=[], space=0.0, skew_deg=skew,
                                notes={"reason": "could not estimate staff spacing"})
        merged = merge_fragments(cands, x_ref, tolerance=0.45 * space)
        groups = comb_staves([y for y, _ in merged], space)
        x0 = int(np.median([c.x0 for c in cands]))
        x1 = int(np.median([c.x1 for c in cands]))
        staves = [
            Staff(lines=g, space=float(np.median(np.diff(g))), x0=x0, x1=x1)
            for g in groups
        ]
        systems = group_systems(staves, space, page.index, factor=self.system_gap_factor)
        return DetectedPage(
            page=page,
            image=image,
            systems=systems,
            space=space,
            skew_deg=skew,
            notes={"line_candidates": len(cands), "merged_lines": len(merged)},
        )


register("projection", ProjectionDetector)
