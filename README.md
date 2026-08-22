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
| `name:Perc` | match the printed instrument label (needs `tesseract` on PATH) |

The reliable way to find the index is to look:

```console
sheeets inspect score.pdf --pages 3 --overlay out/
```

writes the page with every staff boxed and numbered from the top *and* from the
bottom, so you can read the number off the instrument you want. `--labels out/`
writes the label column beside each staff as its own small image, which is the
same answer without OCR.

`name:` reads the labels instead, and it is tolerant: on the score this was
built against the nineteen names come back carrying the staff's own bracket and
the odd stray tick — `". Timpani ["`, `"_y Eb Bass -~"` — and the comparison is
on letters alone, so `name:Timpani`, `name:Euphonium` and `name:Percussion` all
land on the right staff. The staff that matched is remembered, so a score that
prints its names on the first page only still works, and a 27-page score costs
nineteen OCR calls rather than five hundred. It is still a convenience: check
it with `--overlay` before trusting a part to it.

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
that guesses, and it guesses plausibly, so the run checks itself and tells you
where to look:

- every measure is added up against its own time signature — one that does not
  add up is wrong, no argument;
- the number of bars the *source* holds is worked out before any recognition
  happens, and compared with the number of measures that came back.

```
Optional Percussion: 402 measures read by audiveris, 414 bars counted in the
scan, 8 measure(s) that do not add up — needs proofreading
  score page -> measures (bars seen in the scan / measures read):
    p3      1-13   (23 / 13)
    p16   204-221  (18 / 18)  4 suspect
  measures to proofread: 211(p16), 218(p16), 219(p16) …
```

So a flagged bar is never just a number: it comes with the page of the score it
came from, which is what makes fixing it quick.

**If the source is a part, it is checked against what it prints about itself.**
An engraved part numbers the first bar of every system, and puts a count over
every multi-measure rest. Those two numbers together say exactly how many bars
each system holds — including the ones hidden inside a rest, which is the thing
recognition is worst at. Sheeets reads them and makes the recognition agree:

```
403 bars, from the bar numbers printed on the part (21 of 22 systems carry one)
  page 1 system 6: one multi-bar rest could not be read; the bar numbers make it 24
  page 1 system 6: a multi-bar rest read as 4, the page prints 34
  page 1 system 6: bar 5 is a 24-bar rest on the page and was not read as one — put back
  page 1 system 1: 3 bar(s) the page has and the recognition does not; put in
                   as rests so the numbering stays right — proofread them
```

On a publisher's timpani part of a 401-bar overture that is the difference
between 255 measures and 402: Audiveris had dropped the tens digit off every
two-digit rest count, and nothing inside the MusicXML could show it. Every
change is listed, and where the bars cannot be recovered they still go in as
rests — a part whose bar numbers do not match the conductor's score is no use
at a rehearsal, so the numbering is kept and the bad bars are named.

**Installing an engine.** Neither is bundled. Audiveris is much the better of
the two and takes a build; these are the steps that worked here (Ubuntu 24.04):

```console
sudo apt install openjdk-21-jdk tesseract-ocr tesseract-ocr-eng lilypond
git clone https://github.com/Audiveris/audiveris && cd audiveris
git checkout 5.6.3          # master needs Java 25; 5.6.3 builds on 21
./gradlew :app:installDist
export SHEEETS_AUDIVERIS=$PWD/app/build/install/app/bin/Audiveris
export TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
```

oemer is one command — `pip install oemer` — but it needs `numpy<2` and
`onnxruntime==1.16.3` alongside it, so give it its own virtualenv and point
`SHEEETS_OEMER` at that. `sheeets engines` then says what it can see.

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

## A book with every part in it

Band libraries often hold one PDF per piece with every player's pages inside
it, one after another. `sheeets parts` finds the boundaries:

```console
$ sheeets parts book.pdf --split parts/
book.pdf: 20 part(s), title read as 'rulebritannia'
  p1   1-3          3 page(s)  Soloist
  p4   4-4          1 page(s)  Soprano
  p5   5-6          2 page(s)  Solo Cornet
  ...
  p27  27-28        2 page(s)  Bass Eb
  p29  29-30        2 page(s)  Bass Bb
  p31  31-31        1 page(s)  Percussion
  wrote 20 file(s) to parts/
```

It works off the **title**: every part's first page carries it at the top next
to that player's name, and no continuation page does. The title is found as the
longest run of letters that recurs across the headers, compared letters-only so
that "RULE BRITANNIA." and "RULE B RITANNIA”" are the same string. Where OCR
truncates it, two weaker signals make up the difference — enough of the title
to be unmistakable, and a line that *begins* with a player's name.

`--split DIR` writes one PDF per player; `--manifest FILE.json` writes the same
list as fleet cases, so a book can be added to a test fleet in one command.
Either way you can also skip the splitting entirely and pass `--pages 5-6`
straight to `extract`.

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

**Measured, over a fleet of ten real scans** — a bound score, a clean part, two
photocopies, a crooked scan, a born-digital drum-kit part, three parts stacked
on one page, a hand-copied manuscript and a 32-page book holding every part in
turn. Every staff on every page is found, and the book is split into its twenty
parts by name. The music is copyright and is not in this repository; see
`FLEET.md`.

**Measured, for the retype** — one piece read three ways:

| | Optional Percussion, from the score | Timpani, from the score | Timpani, the publisher's part |
|---|---|---|---|
| measures read | 402 | 402 | 402 |
| that do not add up | 41 (10 %) | 8 (2 %) | 6 (1.5 %) |
| rehearsal marks recovered | A–O, all fifteen | A–O | none readable |

The piece is 401 bars. Two of those columns are the same instrument read two
ways — the score's timpani staff and the publisher's own printing of that part
— and they agree at 402 measures. The third is the harder job on the same page:
percussion is two voices of unpitched noteheads with nothing to check a pitch
against, and it comes out at five times the error rate.

**Not verified:**

- Any other score. One publisher, one engraver, one scanner.
- Handwritten or very old engraving; pages with a curl rather than a tilt (the
  deskew is one angle for the whole page).
- The retype on anything but those two parts. Detection is good on all ten
  fleet cases; recognition has been measured on two.
- Rehearsal marks on a part rather than a score. On the one part tried, none
  could be read with confidence, and the app says so instead of inventing them.

## A note on copyright

Scores are usually somebody's copyright. Sheeets is for making a part from music
you already have the right to use — your own scans, your band's library, public
domain editions. It keeps no copy of anything: no score is committed to this
repository, and the tests draw their own synthetic pages (`tools/make_fixture.py`).

## Tests

```console
python -m pytest          # 65 tests, no score and no OMR engine required
```

## Licence

GPL-3.0-or-later; see `LICENSE`. That covers this code and nothing else — the
music you put through it is yours or somebody else's, and the section above
says what that means in practice.
