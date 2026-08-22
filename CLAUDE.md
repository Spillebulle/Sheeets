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

## Two halves, and the difference between them

`extract` is geometry: it cuts the right staff out of the scan. It can be
checked by looking, and it is verified against a real score.

`retype` is recognition: an OMR engine reads the music and LilyPond sets it
again. It **guesses**, and it guesses plausibly. Everything in that half is
built around not trusting it: every measure is added up against its time
signature, the bars in the scan are counted before recognition happens so a
missing bar can be seen at all, and the result carries a `trustworthy` flag and
a page-by-page report rather than prose.

Never soften that. If a change makes the retype path look more confident than
its numbers justify, it is the wrong change.

## A part carries evidence a score does not

When the source is a *part* — one staff to a system — the page prints its own
answer key: a bar number over every system after the first, and a count over
every multi-measure rest. `barnum.py` reads both, and `retype._reconcile` makes
the recognition agree with them. This is the only outside check the retype
half has, and it caught a failure nothing internal could: a 401-bar timpani
part recognised as 255 measures, every measure of it well formed.

Rules that keep it honest, and that must survive a refactor:

- **Read it only where it belongs.** The numbers above the top staff of a
  *score* system are the top instrument's, not the part's. `_is_a_part` gates
  the whole thing on every system having exactly one staff.
- **Arithmetic before OCR.** Once the printed bars are counted, the total of a
  system's rests is forced by the bar numbers. One unreadable count is solved
  for; one wrong count is corrected only if a single change fixes the sum *and*
  the new value looks like a misreading of what was read. Anything less certain
  is refused and reported.
- **A restored rest is not a guess** — a multi-measure rest has no content
  beyond its length — but changing a rest's length silently would be. Every
  change is reported and lands in the report's warnings.
- **Padding is for the numbering, not for the music.** Where bars cannot be
  recovered they go in as rests so that bar 300 is still bar 300, and they are
  named for proofreading. Never quietly.

## Shape

Stages are independent and registered, and that is worth protecting:

- `sources.py` → `detect/` → `layout.py` → `select.py` → `crop.py` →
  `reflow.py` → `export/`, wired only in `pipeline.py`.
- A stage may not import a later one. `detect/` must not know what an exporter
  is; `export/` must not know how staves were found.
- New detector, exporter or recogniser: implement the protocol and `register()`.
  No `if` in the pipeline.
- `recognize/` is a seam, not a feature. No OMR engine ships here; two are
  driven as external programs (`recognize/engines.py`) and found by environment
  variable. Writing half an engine would be worse than none.
- `score_xml.sanitize` may only make *structural* repairs — things that stop an
  engraver dead. It must never change which notes are played, and every repair
  it makes is reported.

## The fleet

`FLEET.md` describes a set of real scans the pipeline is run over — a bound
score, a clean part, a photocopy, a crooked scan, a photograph, a
born-digital part, stacked parts, manuscript, a book of parts. **The music is
copyright and is never committed**; the manifest and the PDFs live outside the
repository and `tools/fleet.py` is pointed at them.

Run it before and after any change to `detect/`, `layout.py`, `crop.py` or
`reflow.py`. Six real faults came out of it that no synthetic page showed, and
they are listed in NOTES.md. A change that improves one case and quietly ruins
another is the normal failure mode here, and the fleet's change column is the
only thing that catches it.

## Things that will look like shortcuts and are not

- Rendering below 300 dpi because it is faster. At 150 dpi this score loses a
  third of its staves and says nothing about it.
- Assuming the deskew direction instead of re-measuring it.
- Filtering staff-line candidates by bounding-box height. Use thickness
  (`area / width`); a tilted line has a tall box.
- Cutting a system anywhere but at a barline.
- Committing a score. They are copyrighted and they are megabytes; the tests
  draw their own pages with `tools/make_fixture.py` and the fleet keeps its
  music outside the repository (`FLEET.md`).
- Judging a detector change on the synthetic fixtures alone. They are upright,
  evenly printed and complete, which is exactly what real paper is not.
- Stopping at the first binarisation that "looks reasonable". Eleven evenly
  spaced staves look perfectly healthy on a page that has thirteen.
- Taking the longest run of rehearsal letters as the right one. Loosening the
  box detector doubles what is found and the longest run gets *longer* — A to U
  on a piece with A to O. A run says what was read is real; it says nothing
  about what else was invented. A run that does not begin at A is not placed.
- Handing tesseract a tighter, cleaner, bigger crop. It does its own
  thresholding and layout work on what it is given. Isolating a rehearsal
  letter from its frame and enlarging it — both plausible, both measured, both
  broke a run that the plain crop reads correctly. The same enlargement is
  what *fixed* the rest counts. Measure per case; do not generalise.
- Believing a barline count. It made 414 of a 401-bar part. Where the page
  prints bar numbers, they are the count.

## Commands

```console
pip install -e .[dev]
python -m pytest                                    # 110 tests, no score needed
sheeets engines                                     # what is installed here
sheeets inspect score.pdf --pages 3- --overlay out/ # what is on the page
sheeets extract score.pdf --part bottom -o part.pdf
sheeets retype  score.pdf --part bottom -o fresh.pdf --workdir work/ --reuse
```

`retype` needs two outside programs, neither bundled: an OMR engine (Audiveris
5.6.3 is much the better of the two wired up; it needs Java 21, and master
needs Java 25, so build the tag) and LilyPond for the engraving. Always pass
`--workdir` and `--reuse` while working on the joining, checking or engraving
stages — recognition is the slow part and re-doing it wastes an hour.
