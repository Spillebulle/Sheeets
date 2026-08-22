# Sheeets

Cut one part out of a scanned score and set it as its own sheet music.

You have a conductor's score as a PDF — twenty staves to a page, one system per
page — and you want the percussion line on its own, big enough to play from.
Sheeets finds the staves, takes the one you asked for off every page, cuts each
system at its barlines into pieces that fit the paper, and lays them out as a
part.

```python
from sheeets import extract_part

extract_part("score.pdf", part="bottom", pages="3-", out="percussion.pdf")
```

```console
$ sheeets inspect score.pdf --pages 3-
score.pdf: rendered at 300 dpi
  p3: systems=1 staves=[19] space=10.6px (0.90mm) skew=+0.24deg
  p4: systems=1 staves=[19] space=10.9px (0.92mm) skew=+0.35deg
  ...
  total staves: 513

$ sheeets extract score.pdf --part bottom --pages 3- -o percussion.pdf \
      --name "Optional Percussion" --title "Ruslan and Ludmila · Overture"
Optional Percussion: 81 piece(s) from 27 page(s) -> percussion.pdf
```

## Install

```console
pip install -e .          # numpy, pillow, pymupdf, scipy
pip install -e .[dev]     # and pytest
```

## Choosing the part

`--part` (or `part=`) takes:

| spec | means |
|---|---|
| `bottom`, `top` | the last or first staff of each system |
| `-1`, `-2`, `17` | by position; negative counts from the bottom, as in Python |
| `17..18` | a run of staves, for a part printed on two |
| `all` | every staff — which is how an already-extracted part passes through |
| `name:Perc` | match the printed instrument label (needs OCR; see below) |

The reliable way to find the index is to look:

```console
sheeets inspect score.pdf --pages 3 --overlay out/
```

writes the page with every staff boxed and numbered from the top *and* from the
bottom, so you can read the number off the instrument you want. `--labels out/`
writes the label column beside each staff as its own small image, which is the
same answer without OCR.

## Output

The suffix of `--out` decides the format:

- **`.pdf`** — the part, laid out to be played from. `--staff-mm` sets how big
  (1.75 mm between staff lines is a normal engraved part; the score it came from
  is nearer 0.9 mm), `--page`/`--landscape`/`--margin-mm`/`--gap-mm` set the
  paper, `--show-sources` prints the source page number beside each system.
- **a folder** — one PNG per piece, named in playing order.
- **`.json`** — the geometry: every staff found, every band cropped, every cut
  made, in pixels plus the dpi to turn them into millimetres. This is the seam
  for anything that wants to edit or re-run the layout.
- **`.musicxml`** — needs an optical music recognition engine, which Sheeets does
  not include. See "Retyping" below; without one it fails with a sentence saying
  so rather than writing an empty file.

## Retyping: fresh files rather than a cropped scan

`extract` gives you the scan, cut up and enlarged. `retype` gives you *new*
sheet music: the part is read by an optical music recognition engine and set
again by LilyPond, so the output is clean vector notation with no scanner grain,
and a MusicXML file you can open in MuseScore, Sibelius or Dorico and edit.

```console
$ sheeets engines
optical music recognition:
  [yes] audiveris
  [no ] external
  [yes] oemer
engraver:
  [yes] lilypond GNU LilyPond 2.24.3

$ sheeets retype score.pdf --part bottom --pages 3- -o fresh.pdf \
      --name "Optional Percussion" --workdir work/ --report proof.json
```

**Read the report before you play from it.** Recognition is the one part of this
that guesses, and it guesses plausibly, so the run checks itself two ways and
tells you where to look:

- every measure is added up against its own time signature — one that does not
  add up is wrong, no argument;
- the number of bars the *scan* holds is counted from the barlines found during
  extraction, before any recognition happens, and compared with the number of
  measures that came back.

```
Optional Percussion: 192 measures read by audiveris, 400 bars counted in the
scan, 64 measure(s) that do not add up — needs proofreading
  score page -> measures (bars seen in the scan / measures read):
    p3      1-13   (12 / 13)
    p4     14-29   (16 / 16)  2 suspect
  measures to proofread: 1(p3), 4(p3), 19(p4) …
```

So a flagged bar is never just a number: it comes with the page of the score it
came from, which is what makes fixing it quick.

**Which engine, and what to feed it.** Two are wired up: `oemer` (pip install,
neural, quick to set up) and `audiveris` (Java, has to be built, much better).
Neither ships with Sheeets. By default the engine is handed **the original score
pages** and the wanted part is picked out of its answer by staff position —
Audiveris reads a nineteen-stave system as nineteen parts, and each keeps its
own clef. `--read-from part` hands it the extracted part instead, which sounds
simpler and reads worse: the draft's lines are pieces of systems, so most begin
mid-phrase with no clef.

`--jobs 3` reads three pages at once (the engines are subprocesses, and a
nineteen-stave page takes Audiveris about four minutes). `--workdir` keeps the
page images and the per-page MusicXML; `--reuse` then skips recognition and
re-does only the joining, checking and engraving, which turns a repeat run from
an hour into seconds.

Because recognition in score mode is *per page* and the part is chosen
afterwards, a second part from the same score costs nothing:

```console
sheeets retype score.pdf --part -2 -o timpani.pdf --workdir work/ --reuse
```

`--proof proof.pdf` writes the scan of every page whose bars were flagged, with
the measure numbers to look at. The loop is: read the flag, look at the bar in
the proof sheet, correct it in the MusicXML, done.

**The whole process, start to finish:**

```console
sheeets inspect score.pdf --pages 3 --overlay out/     # which staff is the part
sheeets extract score.pdf --part bottom --pages 3- -o part.pdf     # faithful
sheeets retype  score.pdf --part bottom --pages 3- -o fresh.pdf \
        --workdir work/ --jobs 3 --proof proof.pdf --report report.json
```

The extracted part is finished work; the retyped one is a draft with a list of
what to check.

## How it works

Six stages, each replaceable, wired together in `pipeline.py`:

| stage | module | contract |
|---|---|---|
| read | `sources.py` | `PageSource` → greyscale pages at a dpi |
| find staves | `detect/projection.py` | `StaffDetector` → `DetectedPage` |
| group | `layout.py` | staves → systems |
| choose | `select.py` | `PartSelector` → which staves are the part |
| crop | `crop.py` | staff + neighbours → a band on the page |
| reflow | `reflow.py` | band + barlines → pieces that fit the paper |
| write | `export/` | `Exporter` → PDF, images, JSON, MusicXML |

and, for retyping, three more:

| stage | module | contract |
|---|---|---|
| recognise | `recognize/` | `Recognizer` → MusicXML per page |
| join and check | `score_xml.py` | merge, repair, add up every bar |
| engrave | `engrave.py` | MusicXML → a fresh PDF, via LilyPond |

The detector works on the ink: keep pixels that sit in a long horizontal run,
label what survives, keep the components that are wide and thin, fit a line to
each, take the median slope as the page's skew, rotate the page flat, then find
groups of five evenly spaced lines. `NOTES.md` has the measurements behind every
threshold, and the four traps that cost real time.

## Extending it

Nothing in the pipeline knows about the others' internals, so:

- **another detector** — implement `detect(page) -> DetectedPage` and
  `detect.register("mine", MyDetector)`. A model-based one would slot in here.
- **another output** — implement `write(extraction, path, **options)` and
  `export.register("mine", MyExporter())`.
- **a single part as input** — `--part all` treats every staff on the page as
  the part, so a part PDF passes straight through to the exporters (or to a
  recogniser).
- **another OMR engine** — implement `recognize_page(image, out_dir) -> Path`
  and `recognize.register("mine", MyEngine())`. Anything that reads a folder of
  images and writes MusicXML needs no code at all:

  ```console
  export SHEEETS_OMR_COMMAND="my-omr --in {input} --out {output}"
  sheeets retype score.pdf --part bottom -o fresh.pdf --engine external
  ```

  The two engines that are wired up are found the same way, by environment
  variable: `SHEEETS_AUDIVERIS` and `SHEEETS_OEMER`.

## What is verified, and what is not

**Measured, against a real 29-page scanned brass band score** (Glinka/Lorriman,
*Ruslan and Ludmila*, 300 dpi, spiral bound, pages scanned alternately upside
down):

- 19 staves found on all 27 music pages, no page short and none over.
- Staff spacing 10.6–11.0 px, skew ±0.03 to 0.59 degrees, corrected on every
  page; the deskew's direction is checked by re-measuring, not assumed.
- The bottom staff (Optional Percussion) extracted from all 27 pages into an
  8-page part, cut at barlines, at 1.75 mm staff size.
- The Timpani staff (`--part -2`) extracted and compared bar for bar against the
  publisher's own Timpani part: same clef, same opening, same music.

**Not verified:**

- Any other score. One publisher, one engraver, one scanner.
- Scores with more than one system per page — the grouping is written and unit
  tested against fabricated geometry, but no real multi-system page has been
  through it.
- Handwritten or very old engraving; pages with a curl rather than a tilt (the
  deskew is one angle for the whole page).
- `name:` selection, which needs OCR that is not installed here.
- MusicXML, which needs an engine that does not exist here.

## A note on copyright

Scores are usually somebody's copyright. Sheeets is for making a part from music
you already have the right to use — your own scans, your band's library, public
domain editions. It keeps no copy of anything: no score is committed to this
repository, and the tests draw their own synthetic pages (`tools/make_fixture.py`).

## Tests

```console
python -m pytest          # 34 tests, no score required
```
