# Notes

What was measured, and what it cost to find out. Everything here was run against
a real scan (Obrasso brass band score of Glinka's *Ruslan and Ludmila* overture,
29 pages, A4 landscape, 300 dpi, spiral bound) or against the synthetic pages in
`tools/make_fixture.py`. Keep it that way: if a number appears here it should be
one somebody printed, not one somebody expected.

## Resolution decides whether any of this works

The staves on a nineteen-stave score are tiny. Measured on this scan:

| render dpi | staff space | staves found on p3 (of 19) |
|---|---|---|
| 150 | 5.5 px | 11, and 0 on two pages |
| 300 | 10.9 px | 19 on all 27 music pages |

At 5 px a staff line, a beam and a slur are the same object to any threshold, so
detection does not fail loudly — it returns a plausible, wrong number of staves.
`PdfSource.native_dpi()` reads the resolution the scan actually holds (here the
embedded images are 2480×3508 on an A4 page, so exactly 300) and `--dpi auto`
never goes below 300.

## Skew is real, and its direction is not obvious

Every page of this scan is out of true, alternating in sign because the book was
turned over between pages: measured skews ran from -0.41 to +0.59 degrees. At
+0.59 degrees a staff line drifts 36 px across the page — three staff spaces,
enough that a full-width projection smears five lines into one grey band.

The first fix rotated the wrong way, which is easy to do: "slope in image
coordinates, y down" and "PIL's `rotate` is counter-clockwise" cancel out to a
sign that has to be tried rather than reasoned about. With the sign backwards
the skew *doubles*, and the page still half-works, which is worse than failing:

| page | measured slope | rotate −θ, residual | rotate +θ, residual |
|---|---|---|---|
| p3 | +0.00422 | +0.00829 | **−0.00016** |
| p16 | +0.00987 | +0.01715 | **+0.00009** |
| p21 | −0.00719 | −0.01383 | **−0.00026** |

So the detector rotates, re-measures, and keeps the direction that flattened the
page. It costs one extra detection on a tilted page and it cannot be got wrong.

## Thin means thin, not short

The first component filter kept "wide and less than 22 px tall" (bounding box).
On the two most tilted pages — p16 and p26, both at 0.57 degrees — that threw
away *every* staff line, because a 2 px line that drifts 36 px has a 38 px box.
Both pages came back with zero staves.

Thickness is `area / width`. A staff line is 2–3 px thick however tilted it is.
That one change took the two dead pages to 19 staves each.

## Five in a row is not how staves are found

Grouping "five consecutive detected lines that are evenly spaced" fails whenever
anything else long and thin lands between two staves — a hairpin, a long slur,
the trill line over the timpani. One intruder breaks the run and the whole staff
is lost, and on this score that cost 5 to 9 staves a page.

Searching for the *pattern* instead — for each unused line, look for four more
at multiples of the estimated spacing, within 35 % — is immune to intruders,
because an extra line simply never gets picked up. Same pages, 19 staves.

Staff spacing itself comes from the gaps between detected lines: inside a staff
there are four small gaps and between staves one big one, so the median of the
smaller 60 % is the spacing even when lines are missing.

## The binding shadow, and the barline it ate

A spiral-bound scan has a black band down one edge — holes and shadow — and it
swaps sides page to page (this scan: left on odd pages, right on even; measured
as 15–20 % ink in the outer 60 px). Cropping the label column pulls it in.

Finding it as "the last full-height dark column within the outer 12 %" was
wrong: the *opening double barline* of a staff is full-height ink about 180 px
in, so the trim jumped to it and swallowed the instrument label sitting between
the two. The shadow has to be **contiguous with the page edge**: walk in from
the edge and stop at the first clear run of 20 px. The label came back.

## Cut the systems evenly, not greedily

A system here is 3 300 px wide at 300 dpi (279 mm). Enlarged to a playable
1.75 mm staff it becomes 525 mm, so it has to be cut into pieces — and the cuts
must be barlines, or bars get sliced in half.

Filling each piece to the brim and letting the last take the remainder left a
two-bar stub at the end of all 27 systems. Deciding how many pieces are needed
first (`ceil(width / max)`), aiming for equal widths and snapping each aim to
the nearest barline within 35 % gives lines that look deliberate. Same score, 87
pieces greedy vs 81 even.

## Barlines: both ends, and don't be fussy about the middle

A barline is a column of ink spanning the staff. So is a note stem — measured on
this percussion part, stems reach about 85 % of the staff height, and at that
threshold a bar of quavers offered a "barline" every couple of centimetres. What
separates them is **ink at both ends**: a stem hangs off a notehead and reaches
one outer line, not both. On p4's percussion staff that took 23 candidates down
to 9.

Being strict about the ends was then wrong in the other direction. Measured on
p3, the real barlines cover 93–95 % of the staff and their top pixel lands one
or two rows *under* the fitted staff line — the fit is a least-squares line
through a scan, not a ruler. Testing the outermost row exactly, at 95 %,
rejected three consecutive barlines and left a 970 px stretch of music with no
legal cut point in it, so the layout put a cut through the middle of bar 4. The
fix: measure coverage over the staff inset by 8 %, and look for the ends within
a small zone rather than on one exact row. Same page, 6 barlines → 12.

Belt and braces on top of that: if the aimed-for cut has no barline within the
snap window, take the furthest barline that still fits rather than cutting where
the aim landed. A short line is a cosmetic problem; a sliced bar is a musical
one.

**And then: one staff is not enough to find a barline at all.** All of the above
reads a single staff, which is fine on a percussion part with a note every other
bar and wrong everywhere else. Counted staff by staff across one system of this
score — a system with 13 bars in it:

| staff | "barlines" found |
|---|---|
| Soprano Cornet | 25 |
| Solo Cornet | 34 |
| 1st Trombone | 16 |
| Timpani | 15 |
| Optional Percussion | 11 |
| Solo Horn (semiquavers throughout) | **43** |

A stem that runs from a ledger line above the staff to the bottom line passes
every test a barline passes, and dense music is full of them. So the cornet part
was being cut at stems.

What a barline has and a stem has not is that **it crosses the other staves at
the same place**. Summing the per-staff hits across the system and keeping the
columns with support from 30 % of the staves collapses the cornet's 43 to the
same 13 the percussion gives, and agrees with Audiveris exactly on three of the
first four pages (17 against 13 on the other, which is the page with the title
block on it). The layout cuts at those columns now, so any part of the score is
cut at the score's own bars.

## What belongs to a staff, and what belongs to the page

A part is unplayable without the words around the staff — "S.Dr.", "+ B.Dr.",
the dynamic under the bar. A fixed pad cannot capture them: 3.5 spaces clipped
"mf + B.Dr." in half, and 6 spaces pulled in the copyright line.

Measured below the percussion staff, distance in staff spaces:

| page | what is there | where |
|---|---|---|
| p4 | `mf + B.Dr.` | 3.1 – 4.9 |
| p3 | `ff`, `S.Dr.` | 0.1 – 2.9 |
| p3 | footnote and `© Copyright 2005 by OBRASSO-VERLAG AG…` | 4.0 – 7.2 |

There is **no clear row** between the last two on p3 — the ink is continuous
from the staff to the copyright — so "grow until a blank gap" cannot separate
them, and neither can distance. What does separate them is how the ink is *set*:
a line of text is one long unbroken stretch, 144–186 px per row for the
copyright, where `mf + B.Dr.` measures 105 px end to end. So the band grows to
the midpoint of the neighbouring staff (or 6 spaces at the edge of the page) and
then gives back any *block* of rows that reads as text.

Block, not row: the top rows of a text line, where only the tall letters reach,
are as sparse as any marking. Judged row by row they pass, and the part comes
out with the tops of "© Copyright 2005 b" sliced along its bottom edge — which
is exactly what the first version did.

## Sizes, for reference

| | staff space |
|---|---|
| this score | 0.90–0.93 mm |
| an engraved part (rastral 4) | ~1.75 mm |
| enlargement needed | 1.88× |

Which is the whole reason the reflow exists: the part is unreadable at score
size, and readable size does not fit the page.

## The cross-check that matters

The one end-to-end check available: the same publisher also sells the Timpani
part, and it was to hand. Extracting `--part -2` from the score and putting it
beside the publisher's own part gives the same clef, the same opening bars, the
same music. That is the strongest evidence so far that the selector picks the
staff a person means, and it is one piece of music — not a guarantee about any
other score.

## Retyping, and what an OMR engine actually does with this

Cropping a scan is geometry and can be checked by looking. Retyping means a
machine reads the music, and it gets things wrong in ways that look right, so
everything here is a measurement rather than an impression.

**The engine matters more than anything else in the chain.** Both were given
the same page — one page of the extracted percussion part, 400 dpi:

| | oemer 0.1.8 | Audiveris 5.6.3 |
|---|---|---|
| staff | a piano grand staff, invented | one staff, correct |
| clef | treble, invented | **percussion**, correct |
| multi-bar rests | lost | kept |
| measures found on the page | 27 | 36 |
| measures that add up | 1 of 27 | 16 of 36 |

oemer is an end-to-end neural model trained on piano scores and it returns a
piano score whatever it is shown. It is a pip install and it will run anywhere,
which is its whole appeal. For a part that is not a piano part it is not usable.

**What to feed it matters nearly as much.** Two ways of using the same engine on
the same music, over all 27 pages:

| | reading the extracted part | reading the score pages |
|---|---|---|
| what the engine sees | lines that are *pieces* of systems, most starting mid-phrase with no clef | complete systems, nineteen staves, every clef in place |
| measures found | 192 | **388** |
| per page | wildly uneven: 1, 7, 9, 30, 34, 42, 4, 5, 2 … | steady: 12-19, matching the scan |

Audiveris reported "19 parts along 1 system" on a raw score page — exactly the
19 staves the detector finds — and the wanted part is then chosen out of its
answer *by staff position*. Choosing by part index would be wrong the moment a
piano or a harp takes two staves, which is why `score_xml.staff_spans` counts
staves and not parts.

**Three ways machine-written MusicXML kills an engraver.** All three were hit on
the first real run, all three are repaired by `score_xml.sanitize`, and each one
is reported so nobody thinks the output is untouched:

1. `<divisions>0</divisions>`. Meaningless, and fatal twice: the validator
   divides by it, and so does musicxml2ly, which dies with a ZeroDivisionError
   inside LilyPond's own `musicxml.py`. Replaced with whatever the rest of the
   document uses.
2. A tuplet that stops without starting. musicxml2ly's `group_tuplets` compares
   an index against `None` and raises a TypeError. The unmatched notation is
   dropped.
3. A note with neither `<type>` nor a positive `<duration>`. LilyPond's error
   path for exactly this case references an undefined variable and raises a
   NameError, so the message it was trying to print never appears. The note is
   dropped, and which bar lost it is reported.

**Checking the result without a human.** Two arithmetic tests catch most of what
OMR gets wrong:

- **Every measure against its own time signature.** A measure whose notes do not
  add up is wrong whatever it looks like. A whole-bar or multi-bar rest
  (`<rest measure="yes"/>`) counts as exactly one bar however its duration is
  written, or every multi-rest reads as an error.
- **Bars in the scan against measures read.** The barline positions were already
  found in order to cut the systems, so the number of written bars in the source
  is known *before* recognition. Nothing inside the MusicXML can reveal a bar
  the engine never saw; this can, and did: 192 measures against 400 bars.

Both are reported per score page, so a suspect measure comes with the page it
came from. That is the difference between "measure 147 is wrong" and a fix that
takes ten seconds.

## Still open

- Multi-system pages. `layout.group_systems` is written and unit tested against
  fabricated geometry; no real page with two systems has been through it.
- Curled pages. Deskew is a single angle per page, and a scan with a curve near
  the binding will not straighten. The detector tolerates it (the line fits are
  per-component) but the crop band will be looser than it needs to be.
- OCR labels. `name:` works through `pytesseract` if it is installed; it has
  never been run here, and the labels on a score are 2 mm high and abbreviated,
  so treat it as a convenience and check with `inspect --overlay`.
- **How good a retype can get — measured, both parts, all 27 pages.**

  | | Optional Percussion | Timpani |
  |---|---|---|
  | bars counted in the scan | 400 | 409 |
  | measures read | 388 | 402 |
  | measures that do not add up | 87 (22 %) | **8 (2 %)** |
  | pages that failed outright | 1 of 27 | 0 |

  The pitched part is nearly clean; the percussion part is a draft. That is the
  expected shape — percussion is two voices of unpitched noteheads with nothing
  to check a pitch against — but it is worth stating plainly rather than
  averaging the two into a claim about "OMR".

  One page (18) failed in Audiveris and the run carried on without it, which is
  the designed behaviour: the other 26 pages are not lost because one is hard.
  Its measures are simply missing from the result, which is exactly what the
  bar-count cross-check is there to reveal.
- **Whether feeding the engine a bigger staff helps.** The draft is rendered at
  `--omr-staff-mm 2.2` and `--omr-dpi 400`; neither number has been varied.
