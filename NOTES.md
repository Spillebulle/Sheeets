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

## What real paper does that drawn pages do not

Everything above was learned from one score. The test fleet (see `FLEET.md`)
added nine more sources — a clean published part, a photocopy with pencil on
it, a crooked scan, a photograph of an old part on a table, a born-digital
drum-kit part, three players stacked on a page, hand-copied manuscript, and a
32-page book holding every part in turn — and each one broke something.

**A staff line is often not found in one piece.** Where print has faded, one
line comes back as five or six fragments of a tenth of the page each. The
width test was applied to fragments, so the line vanished; it is now applied
to the line *after* its pieces are put back together. That recovered two
systems at the top of the crooked part and a whole page of the clean one.

**Staff spacing cannot be measured from the gaps between detected lines.** On
the photograph the print has spread and every line is found twice, four pixels
apart, so half the gaps are 4 px and the estimate halves — the comb then hunts
for five lines 8 px apart and finds *no staff at all on the page*. Measured
from the ink instead: the commonest vertical run of ink is the line thickness,
the commonest run of white is the gap between lines, and the distance from one
line to the next is the two added together. That page went from 0 to 7 systems.

| | thickness | white gap | space |
|---|---|---|---|
| bound score | 2 | 9 | 11 |
| clean part | 2 | 16 | 18 |
| photocopy | 4 | 10 | 14 |
| crooked scan | 3 | 14 | 17 |
| photograph | 6 | 15 | 21 |

**Lines wobble and go missing.** One staff of the clean part had its lines
detected 18, 15, 21, 17 apart where the spacing is 18. Four lines now claim a
staff and the fifth is computed from a least-squares fit, with the fit itself
as the check that the four belong together.

**Music is on a grid, so a hole in the grid is evidence.** A gap of exactly two
staves' spacing in an otherwise even column is a staff that was not found, and
knowing *where* to look makes it safe to look with weaker evidence — three
lines instead of four. That recovers the glockenspiel staff on the
three-player page, whose middle lines are buried under beamed semiquavers.

**One threshold does not fit one page, let alone all of them.** The crooked
part's first three systems are printed in lighter ink than the rest (ink
minimum 97 against 0 further down); a level that keeps them drowns the dense
systems below. Four ways of deciding what is ink are tried and the one finding
the most staves wins — but only after a fast path that asks whether the staves
already found *account for the ink on the page*, because eleven evenly spaced
staves look perfectly healthy on a page that has thirteen.

**What makes staves a system is a barline through them.** Four versions of this
test were wrong, each in a way only one case exposed:

| test | broken by |
|---|---|
| the gap between staves is much bigger than usual | a part, where every gap is the same size: eight systems read as one |
| ink joining them at the left edge | a staff line detected short: a 19-stave system split in two |
| ink joining them anywhere in the gap | manuscript, where a stray stroke joins two systems |
| ink running the full height through both staves | the scan's dark left border, 65 columns of it, running the height of the page and joining everything |

The last one plus "inside the music, not in the page's margin" is correct on
all ten cases.

**A part's first page carries the title.** That is how a book of twenty parts
is cut into twenty files. The page margin is no help — across the book the
first staff sits between 9 % and 26 % down the page whether or not the part
changes. The title is found as the longest run of letters recurring across the
headers, compared letters-only so that "RULE BRITANNIA." and "RULE B RITANNIA”"
are the same thirteen characters.

## What a part prints about itself

A score is a machine's problem; a *part* is easier, and the reason is that it
carries its own answer key. Two things are printed on it that say, exactly,
how many bars it has and where they are.

**The bar number over each system.** Every system after the first is numbered:
9, 27, 41, 51. The difference between two of them is precisely how many bars
lie between, so a part with twenty-two systems comes with twenty-one exact
statements about its own length. Nothing inside the MusicXML can be checked
against anything until this is read; afterwards, every system can be.

**The count over each multi-measure rest.** A rest of 34 bars is one bar of
paper, so the two numbers are needed together.

This mattered because of a failure nothing else could have caught. A
publisher's timpani part of *Ruslan and Ludmila* — 401 bars, printed plainly
above the last system as 398 with four bars after it — was recognised as
**255 measures**, and every measure Audiveris produced was well formed. It had
simply dropped the tens digit off every two-digit rest count:

| the page prints | Audiveris read |
|---|---|
| 16 | 6 |
| 24 | 4 (and once, not a rest at all) |
| 14 | 4 |
| 34 | 4 |
| 27 | 7 |

Reading the page's own numbers and making the recognition agree with them
brings that to **402 measures**, with the first page exact — and it is not a
guess anywhere: a multi-measure rest has no content beyond its length, so a
rest the engine missed can be *restored* rather than approximated.

### How each is found

Both follow the rule the rehearsal marks already follow: find the shape, then
read only the shape's label.

- **The rest** is a thick bar centred on the middle staff line, about seven
  tenths of a space deep, with clear white above and below it. The white has to
  be looked for *between* the staff lines — a window that reaches across a line
  finds ink every time and the test never fires. Measured on the timpani part
  that finds every rest and no barline, stem or beam.
- **The number** is a cluster of digit-sized ink above the staff. Digits of one
  number share a baseline, which is the condition that stops "323" swallowing
  the "(tr)" printed beside it and being thrown out as too tall.

### The sequence is the check, twice over

Neither number is trusted on its own reading.

The bar numbers are chosen *as a set*: each system offers several digit
clusters, and the one that is the bar number is the one that lets the whole
part ascend. That is the same longest-chain treatment the rehearsal letters
get, with two extra conditions that come free from what a system is — the
number cannot climb slower than one per system, and a jump of hundreds in one
system is a misread rather than a very long rest.

The rest counts are then checked by arithmetic, and this is the part that makes
the whole thing safe. Once the printed bars of a system are counted, the total
of its rests is *forced*:

    sum of rests = (bars the numbers demand) − (written bars) + (number of rests)

So one unreadable count is solved for, not guessed — the 24 that no OCR setting
would read came out of this. One *wrong* count can also be solved for, but only
when a single position can be changed to fix the sum **and** the new value looks
like a misreading of what was read there: 4 for 44, 27 for 2. Anything less
certain is refused and reported. A part with a rest of the wrong length is
worse than a part that says it does not know, because a player counting 16 bars
of rest cannot tell they were meant to count 24 until it is too late.

### When it still cannot be worked out

Then the missing bars go in as rests anyway, and are reported. This looks like
the app inventing music and is the opposite: bar numbers are what a part is
*for* at a rehearsal, and three bars missing from system one puts every later
number one system out of step with the conductor's score. Better to hand over
three bars marked "proofread these" than four hundred that cannot be counted
from.

### Two OCR settings, and why there are two

Measured against numbers read off by eye first, on the same page:

| | psm 7 | psm 8 / 13 |
|---|---|---|
| bar numbers (small light italic) | 14–17 of 19 | **18 of 19** |
| rest counts (large bold italic) | **16 of 16** | 11–14 of 16 |

And 8 and 13 agree with *each other* on the wrong answer for the rest counts,
so a majority vote across all three is worse than psm 7 alone. Scale matters as
much as the mode: at about 70 px tall the bold italic 7 of this engraving came
back as 4, 2 and 5 on different pages; at 150 px the same crops read 7 every
time.

## Rehearsal marks on a part, and three ideas that made them worse

Reading marks off a *part* is harder than off a score, and the difference is
not the letters — it is that a part has a dozen systems to a page. Two things
followed from that:

- Search **every** system, not the first. On a score there is one system to a
  page and it made no difference; on the timpani part, looking at the first
  alone found three letters of fifteen and put them in the wrong bars.
- Stop at the staff above. Twelve staff spaces of "empty margin" above a
  system on a part is the *previous system*, and its noteheads and rest counts
  became rehearsal boxes.

The marks are then kept as (system, bar in that system) rather than as a
measure number, because a multi-measure rest is one bar on the page and several
measures in the recognition; the two only line up once the recognised systems
are in hand.

Three further ideas were tried against the score's twenty-two boxes, where the
right answer — A to O — is known. All three are worth recording as **rejected**:

1. **Isolating the letter from its frame** by connected components before
   reading it. Plausible, and it broke the run: C read as K, D as G. Tesseract
   does its own thresholding and layout work on what it is handed, and a tight
   crop takes that away.
2. **Enlarging the letter** to about 150 px, which is exactly what fixed the
   rest counts. It broke the run here too.
3. **Searching over box thresholds** — try 0.30, 0.20, 0.12 and keep whichever
   yields the longest run of consecutive letters. This is the detector's own
   ink-strategy pattern and it looked like the right shape of answer. At 0.20
   the score's page yields fifty boxes and the longest run is **A to U**, on a
   piece that has A to O. A run is good evidence that what was read is real; it
   is not evidence that nothing else was invented.

What *did* help is a rule about the answer rather than about the reading: a run
of rehearsal letters begins at **A**. A run that starts anywhere else is a run
of misreadings that happens to ascend, and it is discarded rather than placed.
On the timpani part that means no marks at all, and that is the honest outcome
— the run in the best reading available there is F to P over marks that are in
fact A to O, and placing it would put the wrong letter over fifteen bars.

## Still open

- Multi-system pages. `layout.group_systems` is written and unit tested against
  fabricated geometry; no real page with two systems has been through it.
- Curled pages. Deskew is a single angle per page, and a scan with a curve near
  the binding will not straighten. The detector tolerates it (the line fits are
  per-component) but the crop band will be looser than it needs to be.
- OCR labels. `name:` works through `pytesseract` if it is installed; it has
  never been run here, and the labels on a score are 2 mm high and abbreviated,
  so treat it as a convenience and check with `inspect --overlay`.
- **How good a retype can get — measured, two sources of the same piece.**

  | | Optional Percussion (from the score) | Timpani (the publisher's part) |
  |---|---|---|
  | pages | 27 of a bound score | 2 |
  | bars the source says it has | 414, by counting barlines | **403**, from the printed bar numbers |
  | measures read | 402 | 402 |
  | measures that do not add up | 8 (2 %) | 6 (1.5 %) |
  | rehearsal marks recovered | A–O, all fifteen | none readable |

  The piece is **401 bars** — the part prints 398 above its last system and has
  four bars after it. So two entirely separate readings, of two different
  printings, by two different routes, agree to within one measure of each other
  and of the truth. That is the strongest evidence the retype has produced.

  Counting barlines made 414 of a 401-bar piece; the printed numbers made 403.
  Where a part carries numbers, they are the count to believe.

  An earlier version of this table reported the Timpani row from a file that
  had in fact been produced from the *score*, renamed. Two rows with identical
  suspect-measure lists is what gave it away, and it is a good reason to keep
  a report's `part` field honest.
- **Whether feeding the engine a bigger staff helps.** The draft is rendered at
  `--omr-staff-mm 2.2` and `--omr-dpi 400`; neither number has been varied.
- **Retyping anything but the two parts from the bound score.** Detection is
  now good on all ten fleet cases; recognition has only been measured on two.
  The fleet runs `--retype` on everything, and nobody has done it yet.
- **The last page of the book of parts.** Its header reads "cm RULE BRITANNIA”
  — nearmmans", with no legible player, so it is called "part 20". It may be a
  second percussion page rather than a part of its own.
