"""The data that moves between stages.

Every stage of the pipeline speaks in these types and nothing else, which is
what lets a stage be swapped out.  Coordinates are always pixels in the page
image the stage was handed, with y running down; a `dpi` travels with the image
so millimetres can be recovered at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class PageImage:
    """One rendered page, greyscale, one byte per pixel."""

    index: int  # 0-based index in the source document
    array: np.ndarray  # shape (h, w), uint8, 255 = white
    dpi: float
    label: str = ""  # what the source calls this page, e.g. "p3"

    @property
    def height(self) -> int:
        return int(self.array.shape[0])

    @property
    def width(self) -> int:
        return int(self.array.shape[1])


@dataclass
class Staff:
    """One five-line staff on one page."""

    lines: list[float]  # y of each line, top to bottom, after deskew
    space: float  # distance between adjacent lines, px
    x0: int  # where the lines start
    x1: int  # where they end
    index: int = -1  # position within its system, 0 = top

    @property
    def top(self) -> float:
        return self.lines[0]

    @property
    def bottom(self) -> float:
        return self.lines[-1]

    @property
    def height(self) -> float:
        return self.lines[-1] - self.lines[0]


@dataclass
class System:
    """Staves that sound together: one horizontal slice of the score."""

    staves: list[Staff]
    page_index: int
    index: int = 0  # position on the page, 0 = topmost system

    def __len__(self) -> int:
        return len(self.staves)


@dataclass
class DetectedPage:
    """A page after detection.

    `image` is the *deskewed* image, so every y in the staves indexes into it.
    """

    page: PageImage
    image: np.ndarray
    systems: list[System]
    space: float
    skew_deg: float
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def staves(self) -> list[Staff]:
        return [s for sysm in self.systems for s in sysm.staves]


@dataclass
class Band:
    """The rectangle one part occupies in one system, before any reflow."""

    page_index: int
    system_index: int
    staff_index: int
    x0: int
    y0: int
    x1: int
    y1: int
    space: float
    music_x0: int  # where the staff lines themselves begin (label excluded)

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


@dataclass
class Segment:
    """A piece of a band that fits on the output page: what actually gets drawn."""

    image: np.ndarray
    band: Band
    chunk: int = 0  # 0 for the first piece of a band
    of: int = 1  # how many pieces the band was cut into
    dpi: float = 300.0

    @property
    def first_of_band(self) -> bool:
        return self.chunk == 0


@dataclass
class Extraction:
    """What a run produced, and enough of the geometry to redo or edit it."""

    part_name: str
    segments: list[Segment]
    source: str
    pages_used: list[int]
    detected: list[DetectedPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
