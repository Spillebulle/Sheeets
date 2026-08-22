"""Run Sheeets over a set of real scores and print how it did on each.

The scores themselves cannot live in this repository — they are under
copyright — so the fleet is described by a manifest file kept outside it,
naming each case and where its PDF is.  What is in the repository is the
harness and the shape of the manifest.

    python tools/fleet.py --manifest ~/sheeets-fleet/fleet.json
    python tools/fleet.py --manifest ... --only festival --retype

Each case reports the same numbers, so the interesting thing is the *contrast*
between them: a clean engraving, a bound score photographed at an angle, a
third-generation photocopy with somebody's pencil on it.  A change that helps
one and wrecks another shows up here and nowhere else.

The results are written as JSON next to the manifest, and the next run prints
the change against them — so this is also the regression test that a unit test
cannot be, because it needs music nobody may redistribute.

Manifest shape:

    {
      "workdir": "~/sheeets-fleet/work",
      "out": "~/sheeets-fleet/out",
      "cases": [
        {"name": "ruslan-perc", "source": "~/scores/ruslan-score.pdf",
         "part": "bottom", "pages": "3-", "note": "from a 19-stave score"},
        {"name": "ruslan-timpani-part", "source": "~/scores/timpani.pdf",
         "part": "all", "note": "the publisher's own part, clean"}
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sheeets import analyse, extract_part
from sheeets.paper import PageSetup


def run_case(case: dict, workdir: Path, out: Path, do_retype: bool) -> dict:
    source = Path(case["source"]).expanduser()
    name = case["name"]
    pages = case.get("pages")
    part = case.get("part", "bottom")
    result: dict = {"name": name, "note": case.get("note", ""), "source": source.name}

    if not source.exists():
        result["error"] = f"missing: {source}"
        return result

    started = time.time()
    _, detected, dpi = analyse(source, pages=pages)
    staff_counts = [sum(len(s) for s in page.systems) for page in detected]
    result.update(
        pages=len(detected),
        dpi=dpi,
        staves_per_page=_summary(staff_counts),
        systems_per_page=_summary([len(page.systems) for page in detected]),
        skew_deg=round(max((abs(p.skew_deg) for p in detected), default=0.0), 2),
        space_px=round(sum(p.space for p in detected) / max(len(detected), 1), 1),
    )

    extraction = extract_part(source, part=part, pages=pages,
                              out=out / f"{name}-extract.pdf",
                              setup=PageSetup(), part_name=case.get("label", name))
    result.update(
        pieces=len(extraction.segments),
        extract_warnings=len(extraction.warnings),
        extract_seconds=round(time.time() - started, 1),
    )

    if do_retype:
        from sheeets.retype import retype

        started = time.time()
        try:
            outcome = retype(
                source, part=part, pages=pages, out=out / f"{name}-retyped.pdf",
                workdir=workdir / name, reuse=True, jobs=case.get("jobs", 3),
                read_from=case.get("read_from", "score"),
                part_name=case.get("label", name), staff_size=22,
                proof=out / f"{name}-proof.pdf",
            )
            result.update(
                measures=outcome.measures_read,
                bars_in_scan=outcome.bars_in_scan,
                suspect=len(outcome.bad_measures),
                guessed=len(outcome.guessed),
                rehearsal=len([w for w in outcome.warnings if "rehearsal" in w.lower()]),
                trustworthy=outcome.trustworthy,
                retype_seconds=round(time.time() - started, 1),
            )
            (out / f"{name}-report.json").write_text(json.dumps(outcome.report(), indent=2))
        except Exception as exc:  # a case that cannot run must not stop the fleet
            result["retype_error"] = str(exc).strip().splitlines()[-1][:160]
    return result


def _summary(values: list[int]) -> str:
    if not values:
        return "-"
    low, high = min(values), max(values)
    return str(low) if low == high else f"{low}-{high}"


def render(results: list[dict], previous: dict[str, dict]) -> None:
    columns = [
        ("case", "name", 24), ("pages", "pages", 6), ("staves", "staves_per_page", 7),
        ("sys", "systems_per_page", 4), ("skew", "skew_deg", 5), ("space", "space_px", 6),
        ("pieces", "pieces", 7), ("meas", "measures", 6), ("bars", "bars_in_scan", 6),
        ("suspect", "suspect", 8), ("guessed", "guessed", 8),
    ]
    print("  ".join(title.ljust(width) for title, _, width in columns))
    print("  ".join("-" * width for _, _, width in columns))
    for row in results:
        cells = []
        for _, key, width in columns:
            value = row.get(key, "-")
            text = str(value)
            was = previous.get(row["name"], {}).get(key)
            if was is not None and was != value and isinstance(value, (int, float)):
                text += f" ({value - was:+g})"
            cells.append(text.ljust(width))
        print("  ".join(cells))
        if row.get("error") or row.get("retype_error"):
            print(f"      ! {row.get('error') or row.get('retype_error')}")
        if row.get("note"):
            print(f"      {row['note']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--only", help="run just the cases whose name contains this")
    parser.add_argument("--retype", action="store_true",
                        help="also read and re-set each part (needs an OMR engine)")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).expanduser()
    manifest = json.loads(manifest_path.read_text())
    workdir = Path(manifest.get("workdir", manifest_path.parent / "work")).expanduser()
    out = Path(manifest.get("out", manifest_path.parent / "out")).expanduser()
    workdir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    history = manifest_path.with_suffix(".results.json")
    previous = {}
    if history.exists():
        previous = {row["name"]: row for row in json.loads(history.read_text())}

    cases = [c for c in manifest["cases"] if not args.only or args.only in c["name"]]
    results = []
    for case in cases:
        print(f"--- {case['name']}", flush=True)
        results.append(run_case(case, workdir, out, args.retype))
    print()
    render(results, previous)
    history.write_text(json.dumps(results, indent=2))
    print(f"\nwritten to {history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
