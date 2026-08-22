"""Sheeets — cut a part out of a scanned score and set it as its own sheet music.

    from sheeets import extract_part
    extract_part("score.pdf", part="bottom", pages="3-", out="percussion.pdf")
"""

from __future__ import annotations

__version__ = "0.1.0"

from .model import Band, DetectedPage, Extraction, PageImage, Segment, Staff, System
from .paper import PageSetup
from .pipeline import analyse, extract_part, write

__all__ = [
    "__version__",
    "extract_part",
    "analyse",
    "write",
    "PageSetup",
    "Band",
    "DetectedPage",
    "Extraction",
    "PageImage",
    "Segment",
    "Staff",
    "System",
]
