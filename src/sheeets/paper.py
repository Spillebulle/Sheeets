"""Paper, and the one number that decides everything: how big a staff should be.

Engraved parts use a staff space of roughly 1.6-1.9 mm (Behind Bars puts a
normal part at rastral 4, about 1.75 mm).  A staff in a nineteen-stave score is
about half that.  So the target size is what sets the enlargement, the
enlargement is what makes each system too wide for the page, and that is what
makes the reflow necessary.  Change `staff_mm` and the whole shape of the output
changes with it, which is why it lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

MM = 72.0 / 25.4  # points per millimetre

PAGE_SIZES_MM = {  # portrait, width x height
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "b4": (250.0, 353.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
    "tabloid": (279.4, 431.8),
}


@dataclass(frozen=True)
class PageSetup:
    size: str = "a4"
    landscape: bool = False
    margin_mm: float = 14.0
    gap_mm: float = 5.0
    staff_mm: float = 1.75

    @property
    def width_mm(self) -> float:
        w, h = PAGE_SIZES_MM[self.size.lower()]
        return h if self.landscape else w

    @property
    def height_mm(self) -> float:
        w, h = PAGE_SIZES_MM[self.size.lower()]
        return w if self.landscape else h

    @property
    def usable_width_mm(self) -> float:
        return self.width_mm - 2 * self.margin_mm

    @property
    def usable_height_mm(self) -> float:
        return self.height_mm - 2 * self.margin_mm

    def width_pt(self) -> float:
        return self.width_mm * MM

    def height_pt(self) -> float:
        return self.height_mm * MM

    def source_width_limit_px(self, space_px: float, dpi: float) -> int:
        """How many source pixels fit across the page once enlarged."""
        if space_px <= 0:
            return 10**9
        scale = self.staff_mm / (space_px / dpi * 25.4)
        return int(self.usable_width_mm / 25.4 * dpi / max(scale, 1e-6))
