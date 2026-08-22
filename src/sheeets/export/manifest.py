"""The geometry, as JSON.

This is the seam for anything later: an editor that lets a person nudge a band,
a recogniser that wants the crops, a second run that should reuse the detection
rather than redo it.  Everything the pipeline decided is in here, in pixels of
the deskewed page, plus the dpi needed to turn those into millimetres.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..model import Extraction
from . import register


def as_dict(extraction: Extraction) -> dict:
    return {
        "sheeets": 1,
        "source": extraction.source,
        "part": extraction.part_name,
        "pages_used": [p + 1 for p in extraction.pages_used],
        "warnings": extraction.warnings,
        "pages": [
            {
                "page": d.page.index + 1,
                "dpi": d.page.dpi,
                "skew_deg": round(d.skew_deg, 4),
                "staff_space_px": round(d.space, 3),
                "systems": [
                    {
                        "index": s.index,
                        "staves": [
                            {
                                "index": st.index,
                                "top": round(st.top, 2),
                                "bottom": round(st.bottom, 2),
                                "space": round(st.space, 3),
                                "x0": st.x0,
                                "x1": st.x1,
                            }
                            for st in s.staves
                        ],
                    }
                    for s in d.systems
                ],
            }
            for d in extraction.detected
        ],
        "segments": [
            {
                "page": seg.band.page_index + 1,
                "system": seg.band.system_index,
                "staff": seg.band.staff_index,
                "chunk": seg.chunk,
                "of": seg.of,
                "band": {
                    "x0": seg.band.x0, "y0": seg.band.y0,
                    "x1": seg.band.x1, "y1": seg.band.y1,
                },
                "size_px": [int(seg.image.shape[1]), int(seg.image.shape[0])],
                "dpi": seg.dpi,
            }
            for seg in extraction.segments
        ],
    }


class ManifestExporter:
    suffix = ".json"

    def write(self, extraction: Extraction, path: Path, indent: int = 2, **_) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(as_dict(extraction), indent=indent), encoding="utf-8")
        return path


register("manifest", ManifestExporter())
