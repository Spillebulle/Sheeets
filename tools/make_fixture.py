"""Draw a score that looks enough like a scan to test against.

Real scores cannot go in the repository — they are somebody's copyright and they
are megabytes — so the tests draw their own: a page of evenly spaced staves with
barlines and note-shaped ink, optionally tilted by a known angle so the deskew
can be checked against a number rather than an impression.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def draw_page(
    staves: int = 8,
    space: int = 11,
    width: int = 3500,
    height: int = 2480,
    top: int = 200,
    left: int = 300,
    right_margin: int = 120,
    bars: int = 8,
    skew_deg: float = 0.0,
    note_rows: tuple[int, ...] = (1, 3),
    line_width: int = 2,
) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    x0, x1 = left, width - right_margin
    staff_height = 4 * space
    gap = (height - 2 * top - staves * staff_height) / max(staves - 1, 1)

    for s in range(staves):
        y_top = top + s * (staff_height + gap)
        for k in range(5):
            y = y_top + k * space
            draw.line([(x0, y), (x1, y)], fill=0, width=line_width)
        for b in range(bars + 1):
            x = x0 + (x1 - x0) * b / bars
            draw.line([(x, y_top), (x, y_top + staff_height)], fill=0, width=3)
        for b in range(bars):
            for n, row in enumerate(note_rows):
                x = x0 + (x1 - x0) * (b + 0.3 + 0.3 * n) / bars
                y = y_top + row * space
                draw.ellipse([x - space * 0.6, y - space * 0.5,
                              x + space * 0.6, y + space * 0.5], fill=0)
                draw.line([(x + space * 0.6, y), (x + space * 0.6, y - 3.5 * space)],
                          fill=0, width=2)

    if skew_deg:
        image = image.rotate(-skew_deg, resample=Image.BICUBIC, fillcolor=255)
    return image


def staff_tops(staves: int, space: int, height: int, top: int) -> list[float]:
    staff_height = 4 * space
    gap = (height - 2 * top - staves * staff_height) / max(staves - 1, 1)
    return [top + s * (staff_height + gap) for s in range(staves)]


def write_pdf(path: Path, pages: int = 2, dpi: int = 300, **kwargs) -> Path:
    images = [draw_page(**kwargs).convert("L") for _ in range(pages)]
    images[0].save(path, save_all=True, append_images=images[1:], resolution=dpi)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--staves", type=int, default=8)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--skew", type=float, default=0.0)
    args = ap.parse_args()
    path = Path(args.out)
    if path.suffix.lower() == ".pdf":
        write_pdf(path, pages=args.pages, staves=args.staves, skew_deg=args.skew)
    else:
        draw_page(staves=args.staves, skew_deg=args.skew).save(path)
    print(path)
