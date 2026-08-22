# The test fleet

The unit tests draw their own pages: tidy, upright, evenly printed, and no use
at all for the question that actually matters — what happens to a photocopy
somebody has written on in pencil. The fleet answers that. It runs the whole
pipeline over a set of real scans and prints the same numbers for each, so a
change that helps one and wrecks another is visible immediately.

**The music is not in this repository and must not be.** Every item in the
fleet is somebody's copyright. What lives here is the harness
(`tools/fleet.py`) and this description; the scores, the manifest naming them,
and the results live in a private directory outside the repo.

## Running it

```console
python tools/fleet.py --manifest ~/sheeets-fleet/fleet.json
python tools/fleet.py --manifest ~/sheeets-fleet/fleet.json --only castell
python tools/fleet.py --manifest ~/sheeets-fleet/fleet.json --retype   # needs an OMR engine
```

Each run writes `fleet.results.json` beside the manifest, and the next run
prints the change against it — so this is the regression test that a unit test
cannot be, because it needs music nobody may redistribute.

Without `--retype` it exercises reading, detection, grouping and layout, which
is quick. With `--retype` it also runs recognition and engraving, which is
slow (minutes per page) and needs Audiveris and LilyPond installed.

## What a fleet should contain

Not "more scans" — *different failure modes*. Each case below earned its place
by breaking something that the others did not. The list is what to aim for
when assembling a fleet from your own library; the private manifest names the
actual files.

| the case | what it is for | what it broke |
|---|---|---|
| **a full conductor's score** | the main job: one part out of nineteen staves, bound, two voices on the wanted staff | nothing new — it is the case everything was built against |
| **a clean published part** | the control: if this is not right, nothing is | many one-staff systems read as one system of eight staves |
| **a photocopy of a photocopy** | grey, speckled, skewed, pencil in the margin | — |
| **a crooked scan** | skew that *varies* down the page, and lighter ink in the first systems | lines cut into fragments; two systems silently lost to a single threshold |
| **a photograph of an old part** | shot on a table, background in frame, a stamp across it, print spread so every line is found twice | staff spacing halved; **zero staves found on the whole page** |
| **a born-digital part** | drum-kit noteheads, very tight semiquaver writing, no scanning artefacts at all | — |
| **three players stacked on one page** | must work taken whole *and* split into one player | the split and the whole gave identical output |
| **hand-copied manuscript** | irregular everything; the metre changes almost every bar | — |
| **a book of every part in one file** | one PDF, each part in a run of pages | (splitting it by part is not built yet) |

Two useful properties of that list: every case is a *part* except the first, so
the fleet is mostly testing the thing a user actually has; and the cases are
ordered by how much they hurt, which makes a regression easy to place.

## The manifest

```json
{
  "workdir": "/home/you/sheeets-fleet/work",
  "out": "/home/you/sheeets-fleet/out",
  "cases": [
    {
      "name": "big-score-perc",
      "source": "/home/you/sheeets-fleet/scores/some-score.pdf",
      "part": "bottom",
      "pages": "3-",
      "label": "Optional Percussion",
      "read_from": "score",
      "note": "why this case exists and what it is meant to catch"
    }
  ]
}
```

`part`, `pages`, `label` and `read_from` are passed straight through to
`extract_part` and `retype`; `note` is printed under the row. A case whose
`source` does not exist is reported as missing and the rest still run, so a
manifest can name a file you have not scanned yet.

`workdir` is worth keeping between runs: recognition is cached there per page,
so a second run with `--retype` re-does only the joining, checking and
engraving.

## Keeping it

The whole fleet is one directory:

```
~/sheeets-fleet/
    fleet.json            the manifest — paths and notes
    fleet.results.json    the last run, for the change column
    scores/               the PDFs; never leaves this directory
    work/                 cached recognition, per case
    out/                  extracted parts, retyped parts, proof sheets
```

Archive it as a whole (`tar czf sheeets-fleet.tar.gz ~/sheeets-fleet`) and keep
it wherever your scores already live — the same place, under the same terms.
It is deliberately self-contained and deliberately not a submodule: nothing in
this repository should ever point at a real file, or a future contributor will
commit one.

If you move the fleet, the paths in `fleet.json` are the only thing to edit.
