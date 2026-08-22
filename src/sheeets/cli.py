"""Command line.

    sheeets inspect score.pdf --pages 3-               # what is on the pages
    sheeets inspect score.pdf --pages 3 --overlay out/ # numbered staves, to look at
    sheeets extract score.pdf --part bottom --pages 3- -o percussion.pdf
    sheeets retype  score.pdf --part bottom --pages 3- -o fresh.pdf
    sheeets engines                                    # what can read music here
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .paper import PAGE_SIZES_MM, PageSetup
from .pipeline import analyse, extract_part
from .retype import retype


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sheeets", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"sheeets {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("score", help="a PDF, an image, or a folder of images")
    common.add_argument("--pages", default=None,
                        help="which pages, 1-based: '3-', '3-8', '1,4,7-9' (default: all)")
    common.add_argument("--dpi", default="auto",
                        help="render resolution; 'auto' reads it off the scan (min 300)")

    ins = subs.add_parser("inspect", parents=[common],
                          help="report the staves found on each page")
    ins.add_argument("--overlay", metavar="DIR",
                     help="write each page with its staves numbered, to identify a part")
    ins.add_argument("--labels", metavar="DIR",
                     help="write the label column beside each staff as its own image")

    ext = subs.add_parser("extract", parents=[common], help="write one part out")
    ext.add_argument("--part", default="bottom",
                     help="bottom | top | all | index (-1, 17) | range (17..18) | name:Perc")
    ext.add_argument("-o", "--out", required=True,
                     help="output.pdf, geometry.json, or a folder for PNGs")
    ext.add_argument("--name", default="", help="what to call the part in the output")
    ext.add_argument("--title", default="", help="heading on the first page")
    ext.add_argument("--staff-mm", type=float, default=1.75,
                     help="staff space on paper; 1.75 is a normal engraved part")
    ext.add_argument("--page", default="a4", choices=sorted(PAGE_SIZES_MM),
                     help="output paper size")
    ext.add_argument("--landscape", action="store_true")
    ext.add_argument("--margin-mm", type=float, default=14.0)
    ext.add_argument("--gap-mm", type=float, default=5.0)
    ext.add_argument("--pad", type=float, default=3.5, metavar="SPACES",
                     help="how much room above and below the staff to keep")
    ext.add_argument("--labels", default="first", choices=["first", "all", "none"],
                     help="keep the instrument label from the score (default: first only)")
    ext.add_argument("--show-sources", action="store_true",
                     help="print the source page number beside each system")
    ext.add_argument("--quiet", action="store_true")

    ret = subs.add_parser("retype", parents=[common],
                          help="read the part with an OMR engine and set it again, fresh")
    ret.add_argument("--part", default="bottom", help="which staff, as for extract")
    ret.add_argument("-o", "--out", required=True, help="the freshly engraved PDF")
    ret.add_argument("--engine", default=None,
                     help="oemer | audiveris | external (default: the first installed)")
    ret.add_argument("--name", default="", help="what to call the part")
    ret.add_argument("--title", default="", help="heading on the first page")
    ret.add_argument("--staff-size", type=float, default=20.0,
                     help="LilyPond staff size for the fresh engraving")
    ret.add_argument("--page", default="a4", choices=sorted(PAGE_SIZES_MM))
    ret.add_argument("--landscape", action="store_true")
    ret.add_argument("--omr-dpi", type=float, default=400.0,
                     help="resolution the engine is fed at")
    ret.add_argument("--omr-staff-mm", type=float, default=2.2,
                     help="staff size of the draft the engine reads")
    ret.add_argument("--workdir", default=None,
                     help="keep the draft, page images and per-page MusicXML here")
    ret.add_argument("--read-from", default="score", choices=["score", "part"],
                     help="give the engine the original score pages (default) or the "
                          "extracted part; the score reads better, see NOTES.md")
    ret.add_argument("--reuse", action="store_true",
                     help="keep the MusicXML already in --workdir instead of reading again")
    ret.add_argument("--report", metavar="FILE.json",
                     help="write the proofreading report (page by page) as JSON")
    ret.add_argument("--quiet", action="store_true")

    subs.add_parser("engines", help="list the OMR engines and the engraver found here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "engines":
        return _engines()
    dpi = args.dpi if args.dpi == "auto" else float(args.dpi)
    if args.command == "inspect":
        return _inspect(args, dpi)
    if args.command == "retype":
        return _retype(args, dpi)
    return _extract(args, dpi)


def _inspect(args, dpi) -> int:
    _, detected, used_dpi = analyse(args.score, pages=args.pages, dpi=dpi)
    print(f"{args.score}: rendered at {used_dpi:g} dpi")
    total = 0
    for page in detected:
        counts = [len(s) for s in page.systems]
        total += sum(counts)
        space_mm = page.space / used_dpi * 25.4 if page.space else 0.0
        print(
            f"  {page.page.label}: systems={len(page.systems)} staves={counts} "
            f"space={page.space:.1f}px ({space_mm:.2f}mm) skew={page.skew_deg:+.2f}deg"
            + ("" if page.systems else f"  <- {page.notes.get('reason', 'nothing found')}")
        )
    print(f"  total staves: {total}")
    if args.overlay:
        n = _write_overlays(detected, Path(args.overlay))
        print(f"  wrote {n} overlay page(s) to {args.overlay}")
    if args.labels:
        n = _write_labels(detected, Path(args.labels))
        print(f"  wrote {n} label strip(s) to {args.labels}")
    return 0


def _extract(args, dpi) -> int:
    setup = PageSetup(
        size=args.page, landscape=args.landscape, margin_mm=args.margin_mm,
        gap_mm=args.gap_mm, staff_mm=args.staff_mm,
    )
    progress = None if args.quiet else (lambda line: print(f"  {line}", file=sys.stderr))
    extraction = extract_part(
        args.score, part=args.part, out=args.out, pages=args.pages, dpi=dpi,
        setup=setup, part_name=args.name, title=args.title, pad_spaces=args.pad,
        labels=args.labels, show_sources=args.show_sources, progress=progress,
    )
    for warning in extraction.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    pieces = len(extraction.segments)
    pages = len(extraction.pages_used)
    print(f"{extraction.part_name}: {pieces} piece(s) from {pages} page(s) -> {args.out}")
    return 0 if pieces else 1


def _retype(args, dpi) -> int:
    progress = None if args.quiet else (lambda line: print(f"  {line}", file=sys.stderr))
    result = retype(
        args.score, part=args.part, out=args.out, pages=args.pages, dpi=dpi,
        engine=args.engine, omr_dpi=args.omr_dpi, omr_staff_mm=args.omr_staff_mm,
        staff_size=args.staff_size, paper=args.page, landscape=args.landscape,
        part_name=args.name, title=args.title, read_from=args.read_from,
        workdir=args.workdir,
        keep=bool(args.workdir), reuse=args.reuse, progress=progress,
    )
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(result.summary())
    print(f"  fresh engraving: {result.fresh_pdf}")
    print(f"  musicxml:        {result.musicxml}")

    if result.spans:
        print("  score page -> measures (bars seen in the scan / measures read):")
        for span in result.spans:
            seen = result.bars_by_page.get(span.source_page)
            suspect = sum(1 for c in result.bad_measures
                          if span.first_measure <= c.number <= span.last_measure)
            flag = f"  {suspect} suspect" if suspect else ""
            print(f"    p{span.source_page:<4} {span.first_measure:>4}-{span.last_measure:<4} "
                  f"({seen} / {span.measures}){flag}")

    bad = result.bad_measures
    if bad:
        shown = ", ".join(
            f"{c.number}(p{result.page_of(c.number)})" for c in bad[:15]
        )
        more = f" (+{len(bad) - 15} more)" if len(bad) > 15 else ""
        print(f"  measures to proofread: {shown}{more}")
    if args.report:
        import json

        Path(args.report).write_text(json.dumps(result.report(), indent=2))
        print(f"  report:          {args.report}")
    if not result.trustworthy:
        print("  read it against the scan before playing from it")
    return 0


def _engines() -> int:
    from .engrave import LilyPondEngraver
    from .recognize import _REGISTRY

    print("optical music recognition:")
    for name in sorted(_REGISTRY):
        engine = _REGISTRY[name]
        mark = "yes" if engine.available() else "no "
        print(f"  [{mark}] {name}")
    engraver = LilyPondEngraver()
    print("engraver:")
    print(f"  [{'yes' if engraver.available() else 'no '}] lilypond "
          f"{engraver.version()}")
    if not engraver.available():
        print("      needed by `retype`; install lilypond (it brings musicxml2ly)")
    return 0


def _write_overlays(detected, folder: Path) -> int:
    from PIL import Image, ImageDraw

    folder.mkdir(parents=True, exist_ok=True)
    for page in detected:
        image = Image.fromarray(page.image).convert("RGB")
        draw = ImageDraw.Draw(image)
        for system in page.systems:
            for staff in system.staves:
                draw.rectangle(
                    [staff.x0, staff.top, staff.x1, staff.bottom],
                    outline=(200, 40, 40), width=2,
                )
                for tag, x in ((str(staff.index), staff.x0 - 60),
                               (str(staff.index - len(system.staves)), staff.x1 + 12)):
                    draw.text((max(0, x), staff.top - 4), tag, fill=(20, 90, 200))
        image.save(folder / f"{page.page.label}-staves.png")
    return len(detected)


def _write_labels(detected, folder: Path) -> int:
    from PIL import Image

    from .ocr import label_box

    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for page in detected:
        for system in page.systems:
            for i in range(len(system.staves)):
                x0, y0, x1, y1 = label_box(system, i, page.image)
                if x1 <= x0 or y1 <= y0:
                    continue
                Image.fromarray(page.image[y0:y1, x0:x1]).save(
                    folder / f"{page.page.label}-s{system.index}-{i:02d}.png"
                )
                written += 1
    return written


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
