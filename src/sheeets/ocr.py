"""Reading the instrument names, when something is installed that can.

Optional on purpose.  The labels on a full score are 2 mm high and abbreviated,
so OCR gets "B. Tbn." wrong often enough that no part should be chosen by it
without a person looking.  `sheeets inspect --labels` writes the label column out
as an image, which needs nothing installed and is always right.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .model import System


class _Tesseract:
    """The tesseract binary, called the way the rest of this app calls it.

    `pytesseract` is a thin wrapper around exactly this subprocess, and having
    it as a dependency meant `name:` selection did not work on a machine with
    tesseract installed and the wrapper not — which is this one, and which is
    why the feature had never once been run.  Two other places here (the
    rehearsal marks and the bar numbers) already shell out; this makes three,
    and no dependency.
    """

    @staticmethod
    def image_to_string(picture, config: str = "") -> str:
        with tempfile.TemporaryDirectory(prefix="sheeets-label-") as tmp:
            path = Path(tmp) / "label.png"
            picture.save(path)
            out = subprocess.run(
                ["tesseract", str(path), "stdout", *config.split()],
                capture_output=True, text=True,
            )
        return out.stdout if out.returncode == 0 else ""


def backend():
    if not shutil.which("tesseract"):
        return None
    try:
        import pytesseract

        return pytesseract
    except Exception:
        return _Tesseract


def label_box(system: System, staff_index: int, image: np.ndarray, spaces: float = 26.0):
    staff = system.staves[staff_index]
    space = staff.space
    y0 = int(max(0, staff.top - 1.5 * space))
    y1 = int(min(image.shape[0], staff.bottom + 1.5 * space))
    x1 = int(max(0, staff.x0 - 0.3 * space))
    # The label column runs from the page's own margin to the staff, and on
    # this score that is twenty-odd staff spaces, not twelve — at twelve every
    # name came back with its first letters missing: "impani", "lugel",
    # "shonium".  Reaching too far left costs nothing, because there is nothing
    # there but paper.
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
        if crop.size == 0:
            out.append("")
            continue
        picture = Image.fromarray(crop)
        # A score's instrument name is about 2 mm high; enlarged it reads far
        # better, the same lesson the rehearsal marks and the bar numbers each
        # had to learn separately.  psm 6 rather than 7 because a long name is
        # set on two lines ("Optional*" over "Percussion").
        scale = max(1, int(round(90 / max(1, crop.shape[0]))))
        if scale > 1:
            picture = picture.resize((picture.width * scale, picture.height * scale),
                                     Image.LANCZOS)
        try:
            text = engine.image_to_string(picture, config="--psm 6")
        except Exception:
            text = ""
        out.append(" ".join(text.split()))
    return out
