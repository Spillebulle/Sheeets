# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

Sheeets takes a scanned score and writes out one part as its own sheet music.
`README.md` says how to use it; `NOTES.md` is the engineering log — every
threshold in the code has a measurement behind it there, and four of them exist
because something plausible was wrong. Read `NOTES.md` before changing a number
in `detect/`, `crop.py` or `reflow.py`.

## The rule this project turns on

**Measure, then write it down.** This is image processing on real paper: every
"obviously correct" threshold here has already been wrong once, and the failures
are quiet — a wrong number of staves, not an exception. So:

- Print what a page actually contains before believing a change helped.
- When you learn something (a dpi, a skew, a threshold that separates two
  things), put the number in `NOTES.md`, not in a commit message.
- Never state that something works against a real score unless a real score has
  been through it. The README's "verified / not verified" split is load-bearing;
  keep it honest.

## Shape

Stages are independent and registered, and that is worth protecting:

- `sources.py` → `detect/` → `layout.py` → `select.py` → `crop.py` →
  `reflow.py` → `export/`, wired only in `pipeline.py`.
- A stage may not import a later one. `detect/` must not know what an exporter
  is; `export/` must not know how staves were found.
- New detector, exporter or recogniser: implement the protocol and `register()`.
  No `if` in the pipeline.
- `recognize/` is a seam, not a feature. There is no OMR engine here and writing
  half of one would be worse than none.

## Things that will look like shortcuts and are not

- Rendering below 300 dpi because it is faster. At 150 dpi this score loses a
  third of its staves and says nothing about it.
- Assuming the deskew direction instead of re-measuring it.
- Filtering staff-line candidates by bounding-box height. Use thickness
  (`area / width`); a tilted line has a tall box.
- Cutting a system anywhere but at a barline.
- Committing a score. They are copyrighted and they are megabytes; the tests
  draw their own pages with `tools/make_fixture.py`.

## Commands

```console
pip install -e .[dev]
python -m pytest                                   # 34 tests, no score needed
sheeets inspect score.pdf --pages 3- --overlay out/ # what is on the page
sheeets extract score.pdf --part bottom -o part.pdf
```
