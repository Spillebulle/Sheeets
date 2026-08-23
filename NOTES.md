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

## The page the player actually reads

Everything above is about getting the notes right. The first time the retyped
timpani part was *looked at* rather than counted, it was correct and unusable,
and none of what was wrong with it appears in any number the run prints. This
is the argument for opening the PDF.

**A multi-measure rest printed as that many empty bars.** Twenty-four bar lines
with nothing between them, which is not something a player counts from. Two
causes stacked on each other:

1. Audiveris marks every measure of a multi-measure rest `print-object="no"` —
   on the page they are not drawn, the thick bar stands for all of them — and
   musicxml2ly takes that literally and writes a **spacer**. Nothing at all is
   drawn. Making whole-bar rests visible again gets `R1*16` out of
   musicxml2ly, which is a real multi-measure rest, drawn and numbered, and
   which is also what MuseScore and Sibelius expect to find.
2. The measures *this app adds* when it lengthens a rest were copied from one
   of the rest's own bars — and an empty `<measure-style/>` left behind in the
   copy is enough to end the rest as far as musicxml2ly is concerned. Nothing
   but the rest survives the copy now.

**Then LilyPond gave a sixteen-bar rest barely more width than a crotchet**,
with its number pressed onto the staff between two barlines a few millimetres
apart. `MultiMeasureRest.minimum-length`, `space-increment` and a little
padding under the number fix it, and they are injected into whatever `\Score`
context musicxml2ly wrote rather than into a second `\layout` block.

**And LilyPond will not break a line for you.** It fills one and then breaks
it, and a multi-measure rest costs it almost nothing, so the part came out with
nine lines of five to eight bars and then one of about thirty — rests squeezed
under their own minimum width, notes touching. There is no LilyPond setting
for "bars per line". There is one for how many systems the whole part gets, and
LilyPond distributes them, which is the same thing said from the other end.

How many bars a line should hold is not a constant, and the interesting part is
that it does not depend on the bars: it depends on **how much is in** one. So
the target is a number of written events to a line, twenty, and the bars follow
from it. The timpani part averages 2.25 events to a bar and lands on nine bars
a line, which is close to what its own publisher does; a part of running
semiquavers lands on four. Between four and twelve either way.

Two things were tried here and are worth not trying again:

- **`SpacingSpanner.base-shortest-duration` and `spacing-increment`.** Widening
  the spacing unit changes where the *early* lines break and leaves the
  over-full one exactly as it was. The line was not over-full because notes
  were too narrow.
- **Putting the breaks in explicitly** — `<print new-system="yes">` every N
  bars, which musicxml2ly turns into a `\break`. This is worse, and the reason
  is a detail of how musicxml2ly handles a second voice: it pads the silent
  voice with one long skip per run of empty bars, and those runs do not line up
  with the other voice's multi-measure rests. A break inside one leaves an
  empty staff line behind and prints the rest twice. LilyPond has to be allowed
  to choose *where*; all it needs is how many.

**Two crashes, both in musicxml2ly, both from OCR.** The fleet was run with
`--retype` for the first time over all ten cases and two produced no PDF at
all:

- A rest can arrive with a duration and no `<type>`: Audiveris knows how long
  the gap is without deciding what rest to draw in it. musicxml2ly dies with
  `'NoneType' object has no attribute 'print_ly'` — LilyPond's own error path,
  naming nothing — and the `.ly` it leaves behind stops in the middle of a bar,
  so the *next* error is a syntax error hundreds of lines later. Every note is
  given a value worked out from its length now. A few lengths no single note
  can be (20 against 12 divisions is five sixths of a bar) are cut to the
  longest that fits, reported, and then padded by the bar filler.
- A smudged tempo marking came back from OCR as `A"egro m0 to al ways`.
  musicxml2ly writes text straight into a LilyPond string, the stray quote
  closed it, and LilyPond died with "EOF found inside string" at the end of the
  file. Quotes and backslashes are taken out of every piece of text.

**And three things at the top of the page.** The instrument name is drawn to
the left of the first system and LilyPond does not grow the indent to fit it,
so "Optional Percussion" printed as "l Percussion" with the rest off the paper;
the indent is worked out from the name. The title printed twice, one line under
the other, because musicxml2ly prints the movement title as a subtitle and
Audiveris fills that in with whatever it read largest on the page — which on a
score page is the title. And the publisher's imprint along the bottom of the
page had been read as **lyrics**, so the part carried "VERLAG AG, 4537
Wicdlisbach," across bar 211 with a stanza mark "1." beside bar 1. What
separates that from a song is not what the words say but how many notes have
one: below one note in ten they are furniture.

## Still open

- ~~Multi-system pages~~ — **eight of the ten fleet cases are one.** A
  publisher's part is nine to thirteen systems to a page, the three-player
  page is four or five, the book of parts five to eleven. What the grouping
  needed in the end was not more unit tests but three signals instead of one:
  a barline joining two staves, equal group sizes, and the gap between them —
  each of which alone gets one of these cases wrong. See "What real paper does
  that drawn pages do not".
- Curled pages. Deskew is a single angle per page, and a scan with a curve near
  the binding will not straighten. The detector tolerates it (the line fits are
  per-component) but the crop band will be looser than it needs to be.
- ~~OCR labels~~ — **run, and it works.** `name:` no longer needs
  `pytesseract`: tesseract is called directly, as the rehearsal marks and the
  bar numbers already do, which is why the feature had never once been
  exercised on this machine. Two things had to change besides. The label
  window reached twelve staff spaces left of the staff where the column is
  twenty-odd, so every name arrived with its first letters missing —
  "impani", "lugel", "shonium". And the match has to be tolerant: read off
  this score all nineteen names come back right but carrying the staff's own
  bracket and a stray tick, `". Timpani ["`, `"_y Eb Bass -~"`, `"= Euphonium
  l"`. Compared on letters alone, with a close match accepted, `name:Timpani`,
  `name:Percussion` and `name:Euphonium` each pick the right staff.

  The staff is then remembered, which matters twice: many scores print the
  names on the first page only, and reading nineteen labels on each of 27
  pages is five hundred OCR calls where nineteen will do.

  Still a convenience, not the thing correctness rests on — `inspect --labels`
  writes the column out as an image and always works.
- **How good a retype can get — measured three ways on one piece.**

  | | Optional Percussion, from the score | Timpani, from the score | Timpani, the publisher's part |
  |---|---|---|---|
  | source | bottom staff of 27 bound pages | second from the bottom, same pages | 2 clean engraved pages |
  | bars the source says it has | **403**, from the printed bar numbers | 403, the same | **403**, from its own printed numbers |
  | measures read | 402 | 402 | 402 |
  | that do not add up | 41 (10 %) | 8 (2 %) | 6 (1.5 %) |
  | rehearsal marks recovered | A–O, all fifteen | A–O | none readable |

  The piece is **401 bars** — the publisher's part prints 398 above its last
  system and has four bars after it, and the retyped percussion ends on a
  fermata at bar 401.

  Two of those columns are the *same instrument* read two ways: the score's
  timpani staff, and the publisher's own printing of that part. They agree at
  402 measures, and both are one over the truth. That is a controlled
  comparison and it is the strongest evidence the retype has produced. The
  third column is the harder job on the same page — percussion is two voices
  of unpitched noteheads with nothing to check a pitch against — and it comes
  out at five times the error rate. Worth stating plainly rather than averaging
  the three into a claim about "OMR".

  Counting barlines made 414 of a 401-bar piece; the printed numbers made 403
  — and 403 from the score's own numbering and 403 from the publisher's part,
  two printings that share nothing but the music. Where a page carries bar
  numbers, they are the count to believe.

  An earlier version of this table had a Timpani column taken from a file
  produced from the *score* and renamed, and then a Percussion column that was
  in fact the score's timpani staff — `--part -2` on this score is Timpani and
  `bottom` is Optional Percussion. Both times the giveaway was two columns
  agreeing too well. If two readings of different music match to the measure,
  suspect the labels before believing the result.

- **Whether feeding the engine a bigger staff helps.** The draft is rendered at
  `--omr-staff-mm 2.2` and `--omr-dpi 400`; neither number has been varied.
- ~~Retyping anything but the two parts from the bound score~~ — **run over
  all ten.** What it found is in FLEET.md; the short version is that the two
  faults were both crashes in musicxml2ly rather than anything in the
  recognition, and that the spread between cases is much wider than any single
  figure suggests.
- **The last page of the book of parts.** Its header reads "cm RULE BRITANNIA”
  — nearmmans", with no legible player, so it is called "part 20". It may be a
  second percussion page rather than a part of its own.
- **Bars that line up in total but not in place.** System 6 of the timpani part
  holds 98 bars and the fresh part gives it 98, but not in the same places: the
  page prints rests of 4, 16, 24, 14, 34 and 3 separated by rehearsal letters,
  and the retype puts a single 73-bar rest at the end of the system. The total
  is forced by the bar numbers and is right; the *distribution* is refused,
  correctly, and `_pad` has nowhere better to put what it must invent.

  It is refused because the arithmetic is genuinely ambiguous. The counts read
  off the page are 44, 16, ?, 14, 34, 3 against a target of 95, so one of them
  is wrong as well as one unreadable — and there are **six** single
  corrections that make the sum work, of which "44 was really 4, so the
  unreadable one is 24" is only one. Audiveris's own reading of the same rests
  ([4, ·, ·, 6, ·, 4, 4, 3, ·]) looks like a tie-break and is not: it drops the
  tens digit off every two-digit count, so its "4" is equally consistent with
  the right answer and with the wrong one. Two witnesses that fail the same way
  are one witness. Something outside the arithmetic is needed — the rehearsal
  letters printed over those rests would do it, which is another reason to want
  them off a part.

  What this costs, and what it does not: the bar *numbering* stays right from
  the next system on, because the total is right; inside the system the numbers
  drift. A player told "from bar 100" is in the wrong place; a player told
  "from letter D" would not be. It is reported as "73 bar(s) the page has and
  the recognition does not — proofread them", and the 73-bar rest is at least
  conspicuous rather than plausible.
- **Trills.** Audiveris returns no `<trill-mark>` and no `<wavy-line>` at all
  from either Ruslan page, and the timpani part has dozens. Nothing downstream
  can put back what was never read, and `words.py` will not help: `tr` with a
  wavy line is not text. Finding them would be a shape hunt of the same kind as
  `marks.find_boxes` — a short horizontal squiggle above a note — and the
  measurement to make first is how often Audiveris misses one.

## Four faults that only the scan could show

The retype had reached the point where every number it printed was healthy:
402 measures against 403 bars on both Ruslan parts, LilyPond silent, the page
fitting the paper. Put page 2 of the fresh timpani part beside page 2 of its
scan and four things are wrong with it, none of which any figure could report.

### An over-long bar poisons every bar after it, and two voices hid most of them

The bar filler shortened a bar that ran past its barline, and refused to look
at any bar holding a `<backup>` — which is every bar with two voices in it, 61
of them on the percussion part. So on the part where it was needed most it
repaired nothing, and from bar 36 the barline grid was off to the end.

Working inside the voices found 113 over-long voices across the fleet where
the old test found a handful. The order things are given back in is the whole
design, least damaging first: the `<forward>` gaps written before a voice
comes in (whitespace — shortening one moves a note), then the voice's trailing
rests, then any other rest in it, and only then the notes at its end.

That last step is capped at half a bar, and the cap is not caution for its own
sake. Every voice in the fleet that overruns by more than half a bar is on a
page where Audiveris printed no `<time>` of its own and the previous page's
carried over; one of them is a bar of five quarters declared 3/8, another is
138 divisions in a bar of 48. Deleting most of a bar to fit a meter that is
itself misread is the worse of two bad answers. With the cap, 113 becomes 34,
and the 34 are all reported as "the time signature is the more likely fault".

Two smaller faults came out of the same measurement. A `<backup>` can step the
cursor back past the start of the bar — Audiveris sizes one for the longest
voice and writes it after every voice — which hides a shorter voice *behind*
the barline where nothing can see it; only an overshoot is corrected, because
a voice that genuinely comes in on beat three is written exactly that way. And
a `<backup>` can be missing altogether: bar 182 of one part is two whole-bar
rests, one per voice, written one after the other, so the second reads as
starting on beat five.

A thing not to repeat: a voice that is too **short** needs nothing done to it.
musicxml2ly pads one with a skip of its own accord — `e4 e4 e4` in a 4/4 bar
comes out `e4 e4 e4 s4` and the bar check passes. Nineteen bars of the
percussion part have a short second voice and every one of them is fine.

### The engraver knew, and nobody asked it

`barcheck failed at: 1/16` had been in LilyPond's log for as long as the fault
had existed. `Engraved.complaints()` reads the log now and the lines that mean
the *music* is wrong — failed bar checks, an unterminated spanner, a
programming error — go into the report's warnings. LilyPond is talkative about
typography; none of that belongs there.

### The barlines were vouching for the wrong witness

The reconciliation lost the timpani part seventy-three bars, and the bisect
put it on the commit that added the barline cross-check. `_page_agrees`
computed how many bars a system ought to hold by **adding up the
multi-measure rest counts read off it** and comparing that with the barlines.
Those counts are the unreliable half — Audiveris drops the tens digit off
them, which is the entire reason `reconcile.py` exists — so the check was
asking the suspect to vouch for the witness. System 6 of that part reads its
rests as 44, 16, ?, 14, 34 and 3, at least a hundred and eleven bars; the
printed numbers say ninety-eight; and the span was thrown out for disagreeing
with counts that were about to be corrected against it.

The barlines can only put a **floor** under a bar number, and the test has to
be one-sided: a system cannot hold fewer bars than it has printed barlines,
and it can only hold more if there is a multi-measure rest to hide them in.

### Words beside the staff: ask which, not what

A percussion part that says which rhythms to play and not which drum is half a
part, and `words.py` had measured that reading them was impossible: three
answers out of ninety-eight runs of text, two of them rubbish. Both halves of
that measurement were wrong in the same way — the question was open.

Two changes make the same crops readable. Only `--psm 7`, tesseract's
single-line mode, suits a two-word label; the earlier attempt voted three
page-segmentation modes against each other and `--psm 13`, which returns noise
at this size, outvoted the mode that was right. And the question becomes "is
this one of two dozen things a part can be told to play, and which?", where
the closeness of the answer is its own filter.

Three settings each cost a real mistake before they were right:

- **One entry per instrument.** "S. Dr." and "Bass Dr." are four characters
  apart. A misread `ff` in front of `S.Dr.` gave `as S.Dr.,`, which scores
  0.91 against *Bass Dr.* Matching word by word rather than whole-line fixes
  that one; folding the spellings of one instrument into a single entry stops
  the rest.
- **Three characters, not two.** Two was chosen to rescue a "Tri." that read
  as "Ti." — 0.80, and no junk in the sample reached it. The sample was one
  part. On the *timpani* part the same setting put "T. Dr.", "B. Dr.", "Cym.",
  "S. Dr.", "Tri.", "Vib." and "Xyl." onto a part that has none of them, every
  one at exactly 0.80 off a two-letter read of something that is not a word:
  `(tr)` — the trill sign — is four fifths of "Tri.". **A vocabulary tuned on
  one part is not tuned.**
- **A stop-list.** A closed vocabulary only works if it is closed on both
  sides, so the nearest neighbour to a reading is allowed to be *nothing*:
  `tr`, `cresc.`, `poco`, the tempo words.

After all three: every correct naming in the measurement comes in at 1.00 and
every wrong one at 0.80 or below, so the line sits above 0.80 rather than
between. What the vocabulary cannot vouch for keeps the honest answer it
always had — a position, mapped to a bar, in the list of markings the fresh
part could not carry.

Then every naming the fleet made was rendered as a contact sheet and looked
at, which is the only verification worth anything here. Thirty-three
markings, thirty-two right — "tamb. on h/h", "Sus.cym. (G#", "Xylophone",
"Tubular bells", "Bass drum", "Tutti, tempo di Marcia." all named correctly
across five parts and three hands — and one wrong: a notehead with a slur
after it, named **Gong**. It is the only one of the thirty-three that a
single enlargement carried on its own; tesseract read "Gon" once and nothing
the other two times. So a fourth rule, and the cheapest of the four: **two of
the three enlargements must point at the same word.** It costs nothing,
because the vocabulary pulls even a poor reading to the right entry — "Gyms.",
"Gyms." and "Cyms." score 0.57, 0.57 and 0.86 and all three name *Cym.*

### What is still missing from the fresh part

Measured against the timpani scan, and worth knowing before the next attempt:

- **Trills.** Audiveris returned zero `<trill-mark>` and zero `<wavy-line>`
  from either page; the part has dozens. Nothing downstream can put back what
  was never read.
- **Rehearsal letters, on a part.** ~~They work on the score and not on a
  part.~~ **Fixed — see "Finding a rehearsal box by its four strokes" below.**
  Both Ruslan parts and the crooked scan carry their letters now.


## Finding a rehearsal box by its four strokes

A band part without rehearsal letters is close to useless at a rehearsal, and
for a long time the app could only get them off a *score*. On a publisher's
part it found 8 of 15 boxes and read 3 of those; the letters were refused, so
the part carried none. Four things were wrong, and only the first is about
image processing.

**The frames are grey.** Measured on a timpani part: no pixel of a rehearsal
box is darker than 100, and most of the frame is lighter than 160. That single
fact defeats a connected-component finder from both sides. Threshold at 160
and the frame arrives in pieces — the "J" box comes out as a 25x40 fragment
scoring 0.13 where 0.30 is wanted. Threshold at 215 and the whole frame is
there, but so is everything else, and the box joins the ties and the bar
number beside it into one component the width of the system.

**So do not look for a blob.** A rectangle is *two tall vertical strokes of the
same height, closed top and bottom, with white between them*, and that
description survives the generous threshold intact. Take the longest vertical
run in each column of the band: on the band holding J, K and L, seventeen
columns of 2480 carry a run of three staff spaces, and they are the six box
sides and nothing else. Then test the **pair** — same height, a plausible gap,
ink along all four edges, not solid in the middle. Fifteen boxes of fifteen,
nothing spurious, and OCR then reads fourteen of them correctly.

Two numbers in that test were wrong first and are worth writing down. The
interior limit was 0.22 and had to be 0.55: a capital letter fills a third to a
half of the space inside its frame, and the four edges are what makes the test
specific — the middle only has to not be solid. And the edge test averaged over
`h/20` rows, which asks a 43-pixel box on a score page to have a frame twice as
thick as it has; it cost ten of the score's twenty-two boxes. Take the *best*
line near each edge instead, which is scale-free.

**Then three faults in what happens to the letters afterwards**, each of which
alone still produced nothing:

- **A box whose letter cannot be read must be kept.** It used to be dropped,
  which was right while the shape test was the generous half. Now the shape
  test is the reliable one, and dropping the box throws away the *position* —
  the one thing that lets a run close over a hole. Fourteen letters read of
  fifteen boxes; kept, the run closes and B goes in where the page has it.
- **The chain must not overwrite a good reading.** It reaches outwards from
  the letters it matched and declares each unused item the next letter without
  looking at it. On the part the chain ran C to O, the item before it read a
  clean "A", the sequence wanted "B" — so it corrected the A, the run then
  began at B, and all fifteen were refused. A clean letter *below* the
  expectation means a box was **missed**, not misread; one *above* it cannot
  belong further back and is a misreading.
- **"A run must begin at A" was too strong.** It was written against a pile of
  misreadings that happened to ascend, and that is worth keeping — but a run
  every letter of which was *read* cannot be shifted along the alphabet, so
  where it begins says only that the boxes before it were missed. One page
  reads a clean B to K, ten letters, nothing corrected, and refusing it placed
  nothing. The rule is now: not starting at A is allowed if the run is at
  least six long and needed no corrections.

## Where a letter may be put, and where it may not

A player trusts a letter, so a letter in the wrong bar is worse than no letter.
Two guards, both of which fired on real parts the first time they were run.

**Not in a system whose bars could not be lined up.** Its total is right and
its insides are not. System 6 of the timpani part holds 98 bars and gets 98,
but as one 73-bar rest at the end instead of the page's 4, 16, 24, 14, 34 and
3 — so C, D, E and F landed on bars 65, 71, 72 and 76 where the page has 82,
106, 120 and 154. `reconcile` now says which systems it could not line up and
those letters are withheld: the part carries A, G, H, I, J, K, L, M, N, O and
says why the other five are missing.

**Not two in one bar, and never out of order.** Rehearsal letters ascend
through a piece; that is checkable, and it catches a mapping that has failed
however plausible each letter looked on its own. On the worst photocopy in the
fleet, where the recognition is ten bars short of the page, G and H both
clamped to the last bar of their system and were engraved on top of each
other. The whole page's letters are refused when that happens.

## Lining up systems the two halves disagree about

"The scan shows 13 system(s) and the recognition 14; the printed bar numbers
were not used" threw away the only outside evidence a page offers, and on the
crooked scan it also threw away ten rehearsal letters that had been read
correctly. Audiveris splits a printed system in two, or the detector loses one
off a crooked page, and neither is rare.

The two sequences can be lined up by what they are made of: each system the
page shows holds a known number of printed bars, counted from its barlines, and
so does each recognised span. Both run in the same order, so this is an
alignment, not a matching — a page system may take up to three recognised spans
(the engine split it) and up to two recognised spans may be left out (the page's
own system was never detected). Measured on the crooked scan, whose thirteen
detected systems hold 10, 7, 6, 5, 5, 7, 7, 7, 9, 8, 7, 6 and 7 bars against
the recognition's fourteen at 9, 10, 7, 5, 5, 5, 6, 7, 7, 8, 8, 7, 6, 6:
leaving out the recognition's *first* span lines the rest up with a
disagreement of four bars in ninety, where pairing them off one for one
disagrees by thirteen. Nothing is accepted unless it is at least twice as good
as pairing off, and the page's letters then land within a bar of where the scan
prints them — checked against the scan for B, D and E, one out for C.

Which also says something about that page: the recognition was right and the
*detector* lost a system, the first one, which is where its ink is lightest.
That is the fault CLAUDE.md records for this case, seen from the other side.
