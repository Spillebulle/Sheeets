"""Choosing which staff is the part.

Selection is deliberately separate from detection: the same detected page can be
asked for the bottom staff, the third from the top, or every staff at once
(which is what "the input is already a single part" looks like from here).

`parse` turns the command line's `--part` into a selector:

    bottom | top | 3 | -1 | 3..5 | all | name:Perc
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import DetectedPage, System


@runtime_checkable
class PartSelector(Protocol):
    @property
    def name(self) -> str: ...

    def select(self, system: System, page: DetectedPage | None = None) -> list[int]:
        """Indices of the staves in this system that make up the part."""


class IndexSelector:
    """One staff by position.  Negative counts from the bottom, as in Python."""

    def __init__(self, index: int, name: str | None = None) -> None:
        self.index = index
        self._name = name or ("bottom staff" if index == -1 else f"staff {index}")

    @property
    def name(self) -> str:
        return self._name

    def select(self, system: System, page: DetectedPage | None = None) -> list[int]:
        n = len(system.staves)
        i = self.index if self.index >= 0 else n + self.index
        return [i] if 0 <= i < n else []


class RangeSelector:
    """A run of staves, for a part printed on two staves (harp, piano, sheeets)."""

    def __init__(self, start: int, stop: int, name: str | None = None) -> None:
        self.start, self.stop = start, stop
        self._name = name or f"staves {start}..{stop}"

    @property
    def name(self) -> str:
        return self._name

    def select(self, system: System, page: DetectedPage | None = None) -> list[int]:
        n = len(system.staves)
        a = self.start if self.start >= 0 else n + self.start
        b = self.stop if self.stop >= 0 else n + self.stop
        return [i for i in range(a, b + 1) if 0 <= i < n]


class AllSelector:
    """Every staff.  This is how an already-extracted part passes through."""

    @property
    def name(self) -> str:
        return "all staves"

    def select(self, system: System, page: DetectedPage | None = None) -> list[int]:
        return list(range(len(system.staves)))


class LabelSelector:
    """Match the instrument name printed to the left of the staff.

    Needs an OCR backend, which is optional and off the default path — the
    labels on a score are tiny and abbreviated ("Rep. Cnt.", "B. Tbn."), so this
    is a convenience, never the thing correctness rests on.  `sheeets inspect
    --labels` writes out the label column as an image so a person can read it
    and pass the index instead, which always works.
    """

    def __init__(self, pattern: str, ocr=None) -> None:
        self.pattern = pattern.lower()
        self._ocr = ocr
        self._cache: dict[tuple[int, int], str] = {}

    @property
    def name(self) -> str:
        return self.pattern

    def select(self, system: System, page: DetectedPage | None = None) -> list[int]:
        from .ocr import read_labels  # imported late: optional dependency

        image = page.image if page is not None else None
        labels = read_labels(system, image=image, ocr=self._ocr)
        hits = [i for i, text in enumerate(labels) if self.pattern in text.lower()]
        return hits[:1]


def parse(spec: str) -> PartSelector:
    spec = (spec or "").strip()
    low = spec.lower()
    if low in {"bottom", "last"}:
        return IndexSelector(-1, name="bottom staff")
    if low in {"top", "first"}:
        return IndexSelector(0, name="top staff")
    if low in {"all", "*", "whole"}:
        return AllSelector()
    if low.startswith("name:"):
        return LabelSelector(spec[5:])
    if ".." in low:
        a, _, b = low.partition("..")
        return RangeSelector(int(a), int(b))
    try:
        return IndexSelector(int(low))
    except ValueError as exc:
        raise ValueError(
            f"cannot read part {spec!r}; try bottom, top, all, an index like -1, "
            f"a range like 17..18, or name:Perc"
        ) from exc
