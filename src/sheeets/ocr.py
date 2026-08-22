"""Reading the instrument names, when something is installed that can.

Optional on purpose.  The labels on a full score are 2 mm high and abbreviated,
so OCR gets "B. Tbn." wrong often enough that no part should be chosen by it
without a person looking.  `sheeets inspect --labels` writes the label column out
as an image, which needs nothing installed and is always right.
"""

from __future__ import annotations

import numpy as np

from .model import System


def backend():
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return None
    from shutil import which

    return pytesseract if which("tesseract") else None


def label_box(system: System, staff_index: int, image: np.ndarray, spaces: float = 12.0):
    staff = system.staves[staff_index]
    space = staff.space
    y0 = int(max(0, staff.top - 1.5 * space))
    y1 = int(min(image.shape[0], staff.bottom + 1.5 * space))
    x1 = int(max(0, staff.x0 - 0.3 * space))
    x0 = int(max(0, x1 - spaces * space))
    return x0, y0, x1, y1


def read_labels(system: System, image: np.ndarray | None = None, ocr=None) -> list[str]:
    engine = ocr or backend()
    if engine is None or image is None:
        return [""] * len(system.staves)
    from PIL import Image

    out = []
    for i in range(len(system.staves)):
        x0, y0, x1, y1 = label_box(system, i, image)
        crop = image[y0:y1, x0:x1]
        try:
            text = engine.image_to_string(Image.fromarray(crop), config="--psm 7")
        except Exception:
            text = ""
        out.append(text.strip())
    return out
