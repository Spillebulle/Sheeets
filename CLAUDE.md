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

A page prints its own answer key: a bar number over every system after the
first, and a count over every multi-measure rest. `barnum.py` reads both and
`reconcile.py` makes the recognition agree with them. This is the only outside
check the retype half has, and it caught a failure nothing internal could: a
401-bar timpani part recognised as 255 measures, every measure of it well
formed.

Rules that keep it honest, and that must survive a refactor:

- **A bar number belongs to the system; a rest count belongs to a staff.**
  That distinction is the whole reason this works on a score and not only on a
  part. The number printed above the top staff counts the same bars for the
  percussion at the bottom as for the cornets at the top, so it is read there
  and used for any staff. The multi-measure rests are read on the staff being
  extracted (`reconcile.staves_by_page`) — read them off the top of a score and
  they are the first instrument's.
- **Nothing is used unless it is a *run*.** `numbers_are_worth_using` wants
  most systems to carry a number; `choose` takes the longest ascending
  selection; `drop_what_the_page_denies` throws out any number that makes
  nonsense of the systems either side of it. A misread number is a plausible
  number in the wrong place and it spoils *two* spans, not one.
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
- **The barlines may only put a *floor* under a bar number.** They are the
  independent witness that catches a number read as something else entirely,
  and the first version of `_page_agrees` used them wrongly: it added up the
  multi-measure rest counts read off the system and refused any bar number
  that disagreed with the total. Those counts are the unreliable half — the
  dropped tens digit is the whole reason this machinery exists — so it was
  asking the suspect to vouch for the witness, and it silently cost a timpani
  part seventy-three bars. What the paper can honestly say is that a system
  cannot hold *fewer* bars than it has barlines, and cannot hold more unless
  there is a multi-measure rest to hide them in.

## Shape

Stages are independent and registered, and that is worth protecting:

- `sources.py` → `detect/` → `layout.py` → `select.py` → `crop.py` →
  `reflow.py` → `export/`, wired only in `pipeline.py`.
- The retype half is `barnum.py` (read the page's own numbers) →
  `recognize/` → `reconcile.py` (make the two agree) → `score_xml.py` →
  `engrave.py`, wired only in `retype.py`.  `reconcile.py` is pure functions
  over a tree and a list of facts; keep it that way, it is the part most
  likely to need arguing with.
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

## Look at the PDF

The retype half checks itself with numbers, and the numbers are worth what they
say — but the first time the retyped timpani part was *looked at* rather than
counted it was correct and unusable: multi-measure rests drawn as two dozen
empty bars, the instrument's name half off the paper, the publisher's imprint
sung across bar 211 as a lyric, and a line with thirty bars on it. None of that
appears in any figure the run prints, and none of it would have been found by
adding another check.

So: open the PDF. Render a page and read it before believing a change to the
engraving helped. `NOTES.md` has the four faults and what each one turned out
to be.

**Then put it beside the scan.** Looking at the fresh part alone is already
worth more than every number the run prints, and it is still not enough: the
faults it cannot show are the ones where something on the page is simply
*absent* from the output, because a page with nothing wrong on it looks fine.
Setting the retyped timpani part next to page 2 of its scan, at the point
where every count agreed and LilyPond had no complaint, showed two whole
classes of loss at once — fifteen boxed rehearsal letters and every one of the
part's trill signs. Neither is in any figure, and neither would ever have been
found by looking at the output on its own.

**And check what the engraver said.** `LilyPondEngraver.engrave` keeps the log
and `Engraved.complaints()` reads it. A failed bar check means the barline grid
is wrong from that point to the end of the part, and no count of measures can
see it: the run that put a timpani part 915 pt wide on a 595 pt page printed
402 measures, 402 bars, six flagged, and one line in a log nobody read.

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
  about what else was invented. A run that does not begin at A is not placed,
  and neither is one that is mostly *correction*: the chain reaches outwards
  and declares each unused candidate the next letter without looking at it,
  which is right for one misread box in a good run and catastrophic otherwise.
  Measured with a generous detector on a publisher's part: twenty-six
  candidates, four letters actually read, and a confident A to Z came back.
- Reading a word off the page by asking what it says. Ask which of a known
  list it is. Two- and three-letter abbreviations at this size are past
  tesseract on their own — the first attempt got three answers out of
  ninety-eight and two were rubbish — and the same crops read correctly once
  the question is "S. Dr., B. Dr., Tri., … or none of them?", because the
  closeness of the answer is then its own filter. Two things had to be right
  as well: `--psm 7` alone (the earlier version voted three page-segmentation
  modes against each other and the noisy one outvoted the right one), and one
  vocabulary entry per instrument. "S. Dr." and "Bass Dr." are four characters
  apart, and a misread `ff` in front of `S.Dr.` scores 0.91 against the wrong
  drum.
- Handing tesseract a tighter, cleaner, bigger crop. It does its own
  thresholding and layout work on what it is given. Isolating a rehearsal
  letter from its frame and enlarging it — both plausible, both measured, both
  broke a run that the plain crop reads correctly. The same enlargement is
  what *fixed* the rest counts. Measure per case; do not generalise.
- Believing a barline count, or checking the printed numbers against one. On a
  part there is no second staff to vote, so a stem crossing the staff counts as
  a barline: the estimate is within a fifth on five of the ten fleet cases and
  **518 against 68** on a tightly written drum-kit part. Two ways of filtering
  those stems out were measured and both are recorded as rejected in
  `reflow.system_barlines` — each fixes the dense cases and destroys the
  photocopies, where nothing has clear paper beside it. Where a page numbers
  its systems, those numbers win outright; the barline count is a fallback and
  is labelled an estimate when reported.

## Commands

```console
pip install -e .[dev]
python -m pytest                                     # 125 tests, no score needed
python -m pytest tests/test_barnum.py                # one file
python -m pytest tests/test_reflow.py::test_a_one_staff_system_still_has_barlines
python -m pytest -k "barline or rehearsal"           # by name

sheeets engines                                      # what is installed here
sheeets inspect score.pdf --pages 3 --overlay out/   # which staff is which
sheeets extract score.pdf --part bottom -o part.pdf
sheeets retype  score.pdf --part bottom -o fresh.pdf --workdir work/ --reuse
sheeets parts   book.pdf -o parts/                   # split a book by part
```

`--part` takes `bottom`, `top`, an index (`-1`, `17`), a range (`17..18`),
`all`, or `name:Timpani`. The entry point is `sheeets` (`pyproject.toml`
`[project.scripts]`); `python -m sheeets.cli` is the same thing and is what to
use from a checkout that is not installed.

**What has to be on PATH.** `lilypond` and `musicxml2ly` for the engraving, and
an OMR engine found by environment variable — `SHEEETS_AUDIVERIS`,
`SHEEETS_OEMER`, or a template in `SHEEETS_OMR_COMMAND`. Audiveris is much the
better of the two and takes a build: it needs Java 21 where master needs Java
25, so build the 5.6.3 tag, and it wants `TESSDATA_PREFIX` pointing at a
tessdata directory with the **legacy** `eng.traineddata` (Ubuntu ships
LSTM-only). `tesseract` itself is called directly — not through `pytesseract` —
for the instrument labels, the rehearsal letters and the bar numbers, so
without it those three go quiet rather than failing.

Always pass `--workdir` and `--reuse` while working on the joining, checking or
engraving stages: recognition is the slow part (Audiveris is minutes a page)
and re-doing it wastes an hour. In score mode the cache is per *page*, so a
second part from the same score costs nothing.

For the fleet, `--only` is the fast loop:

```console
python tools/fleet.py --manifest ~/sheeets-fleet/fleet.json                 # geometry, ~4 min
python tools/fleet.py --manifest ~/sheeets-fleet/fleet.json --only castell --retype
```
