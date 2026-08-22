"""Bar numbers — the one piece of ground truth a part prints about itself.

An engraved part puts a small italic number above the left end of every system
after the first: 9, 27, 41, 51.  It is there for the player, but it is worth
more to a machine than to a person, because it says *exactly* how many bars
have gone before — including the ones hidden inside a multi-measure rest,
which is the number optical recognition is worst at.

Measured on a publisher's timpani part, the engine read 255 written bars where
the printed numbers say the piece is 401 bars long: nearly every multi-measure
rest came back short.  Nothing inside the MusicXML can catch that.  The printed
numbers can, one system at a time, and they can say by how much.

Two things make them readable where a whole page is not.  They sit in a known
place — a small box above the staff's own left end, which is why
`Staff.x0` has to be the staff's real start — and they are digits, so the OCR
question is narrow.  What is *not* narrow is the neighbourhood: a rehearsal
box, a tempo word and a dynamic can share that band.  So the digits are found
as ink first, clustered, and only the leftmost cluster is read.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .reflow import system_barlines


@dataclass(frozen=True)
class BarNumber:
    """What was read above one system, and where."""

    page_index: int
    system_index: int
    value: int | None
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class Candidate:
    """One reading of one cluster of digits above a system."""

    value: int
    x: int
    y: int


def _clusters(
    image: np.ndarray, left: int, right: int, top: int, space: float, threshold: int,
) -> list[tuple[int, int, int, int]]:
    """Digit-sized ink in the band above a staff, grouped into numbers."""
    from scipy import ndimage

    y1 = max(0, int(top - 0.3 * space))
    y0 = max(0, int(top - 5.0 * space))
    left = max(0, int(left))
    right = min(image.shape[1], int(right))
    if y1 - y0 < 4 or right - left < 4:
        return []
    band = image[y0:y1, left:right] < threshold
    labels, _ = ndimage.label(band, structure=np.ones((3, 3), dtype=int))
    pieces: list[tuple[int, int, int, int]] = []
    for k, slices in enumerate(ndimage.find_objects(labels), start=1):
        if slices is None:
            continue
        ys, xs = slices
        height, width = ys.stop - ys.start, xs.stop - xs.start
        # A digit at this size is between two thirds of a staff space and two
        # and a half, and taller than it is wide.  That rejects the staff line
        # itself, a slur, a hairpin, and the frame of a rehearsal box.
        if not (0.6 * space <= height <= 2.6 * space):
            continue
        if not (0.15 * space <= width <= 2.0 * space):
            continue
        if width > 1.4 * height:
            continue
        pieces.append((int(xs.start), int(ys.start), int(width), int(height)))
    if not pieces:
        return []
    pieces.sort()
    groups: list[list[tuple[int, int, int, int]]] = [[pieces[0]]]
    for piece in pieces[1:]:
        last = groups[-1][-1]
        near = piece[0] - (last[0] + last[2]) <= 0.9 * space
        # Digits of one number share a baseline.  Without that condition the
        # "323" above one system swept up the "(tr)" printed beside it and a
        # cluster two lines deep was thrown away as too tall, so the system had
        # no number at all — and a system with no number is a system whose bars
        # cannot be checked.
        level = abs((piece[1] + piece[3] / 2) - (last[1] + last[3] / 2)) <= 0.7 * space
        if near and level:
            groups[-1].append(piece)
        else:
            groups.append([piece])
    out = []
    for group in groups:
        gx0 = min(p[0] for p in group)
        gy0 = min(p[1] for p in group)
        gx1 = max(p[0] + p[2] for p in group)
        gy1 = max(p[1] + p[3] for p in group)
        # One number sits on one line.  A cluster three staff spaces tall has
        # swept up something above or below it — a dynamic, the tail of a
        # slur — and reads as a run-together number ("3231" for 323).
        if gy1 - gy0 > 2.8 * space:
            continue
        if gx1 - gx0 > 6.0 * space:
            continue
        out.append((left + gx0, y0 + gy0, gx1 - gx0, gy1 - gy0))
    return out


# Which of tesseract's page-segmentation modes to ask, per kind of number.
# These were measured, not guessed, against a page whose numbers were read off
# by eye first — and they do not agree, which is why there are two settings
# rather than one:
#
#   bar numbers (small light italic, above the staff's left end)
#       psm 8 and psm 13 got 18 of 19; psm 7 got 14 to 17 depending on scale.
#   multi-measure rest counts (large bold italic, over the thick bar)
#       psm 7 got 16 of 16 at every scale tried; 8 and 13 got 11 to 14, and
#       agreed with *each other* on the wrong answer, so a majority vote across
#       all three is worse than psm 7 alone.
#
# Scale matters as much as the mode.  At about 70 px tall the bold italic 7 of
# this engraving came back as 4, 2 and 5 on different pages; at 150 px the same
# crops read 7 every time.  Two scales are tried and the answers voted.
NUMBER_MODES = ("8", "13")
COUNT_MODES = ("7",)
SCALES = (2, 4)


def _ocr_digits(
    image: np.ndarray, box: tuple[int, int, int, int], pad: int,
    modes: tuple[str, ...] = NUMBER_MODES,
) -> str:
    if not shutil.which("tesseract"):
        return ""
    x, y, w, h = box
    inside = image[max(0, y - pad) : y + h + pad, max(0, x - pad) : x + w + pad]
    if inside.size == 0:
        return ""
    from PIL import Image

    answers: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sheeets-barnum-") as tmp:
        for scale in SCALES:
            picture = Image.fromarray(inside)
            picture = picture.resize(
                (picture.width * scale, picture.height * scale), Image.LANCZOS
            )
            path = Path(tmp) / f"n{scale}.png"
            canvas = Image.new("L", (picture.width + 60, picture.height + 60), 255)
            canvas.paste(picture, (30, 30))
            canvas.save(path)
            for mode in modes:
                result = subprocess.run(
                    ["tesseract", str(path), "stdout", "--psm", mode,
                     "-c", "tessedit_char_whitelist=0123456789"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    answers.append("".join(c for c in result.stdout if c.isdigit()))
    answers = [a for a in answers if a]
    if not answers:
        return ""
    return max(set(answers), key=lambda a: (answers.count(a), -len(a)))


def read_candidates(
    image: np.ndarray, x0: int, top: int, space: float, threshold: int = 160,
) -> list[Candidate]:
    """Every digit cluster above one system, read.  Order: left to right."""
    out: list[Candidate] = []
    pad = max(1, int(round(0.4 * space)))
    window = (int(x0 - 7.0 * space), int(x0 + 12.0 * space))
    for box in _clusters(image, window[0], window[1], top, space, threshold):
        text = _ocr_digits(image, box, pad)
        if text and text.isdigit() and len(text) <= 4:
            out.append(Candidate(int(text), box[0], box[1]))
    return out


def read_page(detected, page_index: int, threshold: int = 160) -> list[list[Candidate]]:
    """Per system on this page, what numbers could be printed above it."""
    out: list[list[Candidate]] = []
    for system in detected.systems:
        if not system.staves:
            out.append([])
            continue
        staff = system.staves[0]
        out.append(read_candidates(detected.image, staff.x0, int(staff.top),
                                   staff.space, threshold))
    return out


def choose(
    per_system: list[tuple[int, int, list[Candidate]]],
) -> tuple[list[BarNumber], list[str]]:
    """One number per system, chosen so the whole page-set ascends.

    Each system offers several digit clusters — the number itself, but often
    also a dynamic misread as a figure, or the neighbouring system's ink caught
    at the edge of the window.  Read one system at a time there is no way to
    tell them apart; read as a sequence there is, because bar numbers ascend
    and nothing else in the band does.

    So this is the rehearsal letters' problem again in another costume, and it
    gets the same answer: take the longest strictly ascending selection over
    the systems in playing order, at most one per system, and drop everything
    that is not on it.  A system with no plausible number simply has none —
    that is the honest answer, and the caller can still use its neighbours.
    """
    items: list[tuple[int, Candidate]] = []
    for slot, (_page, _system, candidates) in enumerate(per_system):
        for candidate in candidates:
            if candidate.value >= 1:
                items.append((slot, candidate))
    if not items:
        return [], []

    best = [1] * len(items)
    previous = [-1] * len(items)
    for i, (slot_i, cand_i) in enumerate(items):
        for j, (slot_j, cand_j) in enumerate(items[:i]):
            if slot_j >= slot_i or cand_j.value >= cand_i.value:
                continue
            # A system holds at least one bar, so the number cannot climb
            # slower than one per system, and a part that jumps hundreds of
            # bars in one system is a misread rather than a very long rest.
            gap = cand_i.value - cand_j.value
            systems = slot_i - slot_j
            if gap < systems or gap > 120 * systems:
                continue
            if best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                previous[i] = j
    end = max(range(len(items)), key=lambda i: best[i])
    chain: list[int] = []
    while end != -1:
        chain.append(end)
        end = previous[end]
    chain.reverse()

    chosen: list[BarNumber] = []
    for i in chain:
        slot, candidate = items[i]
        page, system, _ = per_system[slot]
        chosen.append(BarNumber(page, system, candidate.value, candidate.x, candidate.y))
    notes: list[str] = []
    on_chain = {items[i][0] for i in chain}
    for slot, (page, system, candidates) in enumerate(per_system):
        if candidates and slot not in on_chain:
            notes.append(
                f"page {page + 1} system {system + 1}: read "
                + ", ".join(str(c.value) for c in candidates)
                + " above the staff; none of it fits the run of bar numbers"
            )
    return chosen, notes


def with_first_bar(
    chosen: list[BarNumber], first_page: int, first_system: int,
) -> list[BarNumber]:
    """Put bar 1 in front when the first system printed no number.

    Engravers do not number the first bar of a piece; the first printed number
    is above the second system.  Bar 1 is not a guess, so it is filled in.
    """
    if chosen and (first_page, first_system) < (chosen[0].page_index, chosen[0].system_index):
        return [BarNumber(first_page, first_system, 1)] + chosen
    return chosen


@dataclass(frozen=True)
class MultiRest:
    """A multi-measure rest: the thick bar, and the count printed over it."""

    x0: int
    x1: int
    count: int | None

    @property
    def centre_x(self) -> int:
        return (self.x0 + self.x1) // 2


def multi_rests(
    image: np.ndarray, staff, threshold: int = 160, min_width_spaces: float = 1.2,
) -> list[MultiRest]:
    """Every multi-measure rest on one staff, with the number above it.

    This is the number optical recognition gets wrong most often and the one
    with the largest consequences: Audiveris read the timpani part's rests as
    7, 5, 7, 2, 4, 6 … where the page prints 7, 5, 7, 2, 4, 16, 24, 14, 34 —
    the tens digit dropped from every two-digit count.  A part 146 bars short
    is not a part.

    The glyph is easier to find than to read: a thick bar centred on the middle
    staff line, about seven tenths of a space deep, one and a half spaces or
    more wide, with clear white above and below it inside the staff.  That last
    condition is what separates it from a barline, a stem and a beam, all of
    which cross the middle line too — and the white has to be looked for
    *between* the staff lines, not across them, or the lines themselves answer
    for it.

    Only then is the number read, from the band above, exactly as the bar
    numbers are.  Finding the shape first is what makes the reading narrow
    enough to trust.
    """
    lines = [float(y) for y in staff.lines]
    if len(lines) < 5:
        return []
    space = float(staff.space)
    middle = lines[2]

    def rows(a: float, b: float) -> slice:
        return slice(max(0, int(round(middle + a * space))),
                     max(0, int(round(middle + b * space))))

    ink = image < threshold
    core = ink[rows(-0.28, 0.28)]
    if core.size == 0:
        return []
    solid = core.mean(axis=0) >= 0.9
    clear_above = ~ink[rows(-0.82, -0.45)].any(axis=0)
    clear_below = ~ink[rows(0.45, 0.82)].any(axis=0)
    hit = solid & clear_above & clear_below
    columns = np.nonzero(hit)[0]
    if columns.size == 0:
        return []
    groups: list[list[int]] = [[int(columns[0])]]
    for x in columns[1:]:
        if x - groups[-1][-1] <= max(2, int(0.5 * space)):
            groups[-1].append(int(x))
        else:
            groups.append([int(x)])

    out: list[MultiRest] = []
    pad = max(1, int(round(0.4 * space)))
    for group in groups:
        x0, x1 = group[0], group[-1]
        if x1 - x0 < min_width_spaces * space:
            continue
        count = None
        for box in _clusters_between(image, x0, x1, int(lines[0]), space, threshold):
            text = _ocr_digits(image, box, pad, COUNT_MODES)
            if text and text.isdigit() and 2 <= int(text) <= 999:
                count = int(text)
                break
        out.append(MultiRest(x0, x1, count))
    return out


def _clusters_between(
    image: np.ndarray, x0: int, x1: int, top: int, space: float, threshold: int,
) -> list[tuple[int, int, int, int]]:
    """Digit-sized ink above one span of staff, nearest its middle first."""
    centre = (x0 + x1) / 2
    found = _clusters(image, int(centre - 3.0 * space), int(centre + 3.0 * space),
                      top, space, threshold)
    return sorted(found, key=lambda b: abs(b[0] + b[2] / 2 - centre))


@dataclass
class SystemFacts:
    """What the page itself says about one system."""

    page_index: int
    system_index: int
    number: int | None = None          # the printed bar number, if there is one
    rests: list[int | None] = None     # multi-measure rest counts, left to right
    rest_bars: list[int] = None        # which written bar each of those is
    written: int = 0                   # written bars in the system, from barlines

    def __post_init__(self) -> None:
        if self.rests is None:
            self.rests = []
        if self.rest_bars is None:
            self.rest_bars = []


def survey(detected_pages, threshold: int = 160) -> list[SystemFacts]:
    """Read every system's printed bar number and multi-measure rest counts.

    The two are read together because they check each other: the numbers say
    how many bars a system holds, the rests say where those bars are hiding,
    and a page where the two agree can be trusted without a second opinion.
    """
    per_system: list[tuple[int, int, list[Candidate]]] = []
    facts: list[SystemFacts] = []
    for page in detected_pages:
        index = page.page.index
        for system_index, system in enumerate(page.systems):
            if not system.staves:
                continue
            staff = system.staves[0]
            per_system.append((
                index, system_index,
                read_candidates(page.image, staff.x0, int(staff.top), staff.space,
                                threshold),
            ))
            rests = multi_rests(page.image, staff, threshold)
            # Which written bar each rest sits in.  `system_barlines` returns
            # the barlines it can see, and the one at the very start of a
            # system is not among them — the clef and key sit on top of it — so
            # bar 0 begins at the staff's own left edge and every barline found
            # opens the next bar.  Counting the barlines to the left of a rest
            # therefore gives its index directly.
            columns = system_barlines(page, system)
            facts.append(SystemFacts(
                index, system_index,
                rests=[r.count for r in rests],
                rest_bars=[sum(1 for c in columns if c < r.centre_x) for r in rests],
                written=len(columns),
            ))
    if not facts:
        return []
    chosen, _notes = choose(per_system)
    chosen = with_first_bar(chosen, facts[0].page_index, facts[0].system_index)
    numbers = {(n.page_index, n.system_index): n.value for n in chosen}
    for fact in facts:
        fact.number = numbers.get((fact.page_index, fact.system_index))
    return facts


def bars_wanted(facts: list[SystemFacts]) -> dict[tuple[int, int], int]:
    """How many bars each system holds, where the printed numbers can say.

    Only where two numbers bracket the system: the difference between them is
    the answer, and it is exact.  A system whose own number or whose successor's
    number was not read gets no entry, which is the honest result — the caller
    then leaves that system alone rather than repairing it on a guess.
    """
    out: dict[tuple[int, int], int] = {}
    known = [f for f in facts if f.number is not None]
    for this, following in zip(known, known[1:]):
        span = following.number - this.number
        # Systems in between were not read, so the difference covers all of
        # them and cannot be attributed to this one.
        if facts.index(following) - facts.index(this) != 1:
            continue
        if span > 0:
            out[(this.page_index, this.system_index)] = span
    return out
