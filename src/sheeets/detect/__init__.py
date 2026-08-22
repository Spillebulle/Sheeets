"""Finding staves on a page.

`StaffDetector` is the contract.  One implementation ships (`ProjectionDetector`,
which works on the ink itself); a model-based one would slot in here without any
other stage noticing, as long as it returns the same `DetectedPage`.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ..model import DetectedPage, PageImage


@runtime_checkable
class StaffDetector(Protocol):
    def detect(self, page: PageImage) -> DetectedPage: ...


_REGISTRY: dict[str, Callable[..., StaffDetector]] = {}


def register(name: str, factory: Callable[..., StaffDetector]) -> None:
    _REGISTRY[name] = factory


def get_detector(name: str = "projection", **kwargs) -> StaffDetector:
    if name not in _REGISTRY:
        raise KeyError(f"no detector named {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def available() -> list[str]:
    return sorted(_REGISTRY)


from .projection import ProjectionDetector  # noqa: E402  (registers itself)

__all__ = ["StaffDetector", "ProjectionDetector", "get_detector", "register", "available"]
