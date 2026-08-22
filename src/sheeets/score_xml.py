"""Reading, joining and checking MusicXML.

An OMR engine is handed one page at a time, so what comes back is one MusicXML
document per page and they have to be joined into a single part.  It is done
with the standard library rather than a score library on purpose: the operation
is "concatenate the measures of a single-part score and renumber them", and that
is a dozen lines of ElementTree against a dependency measured in tens of
megabytes.

`check` is the honest half.  OMR gets things wrong, and the cheapest way to know
which bars to look at is arithmetic: a measure whose notes do not add up to its
time signature is certainly wrong, whatever it looks like.
"""

from __future__ import annotations

import collections
import copy
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

# Note type -> length in whole notes.
TYPE_LENGTH = {
    "maxima": 8, "long": 4, "breve": 2, "whole": 1, "half": Fraction(1, 2),
    "quarter": Fraction(1, 4), "eighth": Fraction(1, 8), "16th": Fraction(1, 16),
    "32nd": Fraction(1, 32), "64th": Fraction(1, 64), "128th": Fraction(1, 128),
}


def read(path: str | Path) -> ET.ElementTree:
    return ET.parse(path)


def merge(paths: list[str | Path], part_name: str = "") -> ET.ElementTree:
    """Join single-part MusicXML documents end to end, renumbering the bars."""
    if not paths:
        raise ValueError("nothing to merge")
    return merge_trees([read(path) for path in paths], part_name=part_name)


def merge_trees(trees: list[ET.ElementTree], part_name: str = "") -> ET.ElementTree:
    if not trees:
        raise ValueError("nothing to merge")
    first = trees[0]
    root = first.getroot()
    part = root.find("part")
    if part is None:
        raise ValueError("the first document has no <part>")

    number = 0
    for measure in part.findall("measure"):
        number += 1
        measure.set("number", str(number))

    for tree in trees[1:]:
        other = tree.getroot()
        other_part = other.find("part")
        if other_part is None:
            continue
        for measure in other_part.findall("measure"):
            number += 1
            copied = copy.deepcopy(measure)
            copied.set("number", str(number))
            part.append(copied)

    if part_name:
        for tag in (".//part-name", ".//instrument-name"):
            for node in root.findall(tag):
                node.text = part_name
    return first


def write(tree: ET.ElementTree, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="UTF-8", xml_declaration=True)
    return path


def staff_spans(tree: ET.ElementTree) -> list[tuple[str, int, int]]:
    """(part id, first staff, staff count) for every part, in printed order.

    A part usually occupies one staff, but a piano or a harp takes two, so the
    staff a person points at ("the bottom one, the percussion") cannot be turned
    into a part index by counting parts.  It has to be turned into one by
    counting *staves*.
    """
    out: list[tuple[str, int, int]] = []
    start = 0
    for part in tree.getroot().findall("part"):
        count = 1
        first = part.find("measure")
        if first is not None:
            declared = first.findtext("attributes/staves")
            if declared and declared.isdigit():
                count = max(1, int(declared))
        out.append((part.get("id", ""), start, count))
        start += count
    return out


def select_staff(tree: ET.ElementTree, staff_index: int) -> ET.ElementTree:
    """Keep only the part that holds the given staff (0 = top of the system)."""
    spans = staff_spans(tree)
    if not spans:
        raise ValueError("the document has no parts")
    if staff_index < 0:
        total = spans[-1][1] + spans[-1][2]
        staff_index += total
    chosen = None
    for part_id, first, count in spans:
        if first <= staff_index < first + count:
            chosen = part_id
            break
    if chosen is None:
        raise ValueError(
            f"staff {staff_index} is not in this document "
            f"({spans[-1][1] + spans[-1][2]} staves read)"
        )
    root = copy.deepcopy(tree.getroot())
    for part in root.findall("part"):
        if part.get("id") != chosen:
            root.remove(part)
    for part_list in root.findall("part-list"):
        for entry in list(part_list):
            if entry.tag == "score-part" and entry.get("id") != chosen:
                part_list.remove(entry)
            elif entry.tag == "part-group":
                part_list.remove(entry)
    return ET.ElementTree(root)


TEMPO_WORDS = (
    "presto", "allegro", "andante", "adagio", "largo", "lento", "vivace",
    "moderato", "maestoso", "grave", "tempo", "mosso", "meno", "piu", "più",
    "rit", "ritard", "rall", "accel", "stretto", "cantabile", "marcato",
)


def looks_like_a_rehearsal_mark(text: str) -> bool:
    """A boxed letter or number over the system: A, B, 12, C1."""
    text = (text or "").strip()
    return 1 <= len(text) <= 3 and (text.isupper() or text.isdigit()) and text.isalnum()


def looks_like_a_tempo(text: str) -> bool:
    lowered = (text or "").strip().lower().rstrip(".")
    return any(lowered.startswith(word) for word in TEMPO_WORDS)


def graft_directions(page: ET.ElementTree, target: ET.ElementTree,
                     from_part: int = 0) -> int:
    """Copy the markings a score prints only over its top staff.

    A conductor's score puts the tempo and the rehearsal letters above the first
    staff and nowhere else — they belong to the whole system, not to the piccolo.
    Cut the bottom staff out and they are gone, and a band part without its
    rehearsal letters is not much use at a rehearsal.

    Only what is genuinely the system's is copied: rehearsal marks, metronome
    marks, and words that read as a tempo.  A dynamic or a "solo" over the top
    staff belongs to *that* instrument and is left where it is.
    """
    parts = page.getroot().findall("part")
    if len(parts) <= from_part:
        return 0
    source_measures = parts[from_part].findall("measure")
    target_part = target.getroot().find("part")
    if target_part is None:
        return 0
    target_measures = target_part.findall("measure")

    grafted = 0
    for index, source in enumerate(source_measures):
        if index >= len(target_measures):
            break
        for direction in source.findall("direction"):
            kind = direction.find("direction-type")
            if kind is None:
                continue
            wanted = False
            for child in kind:
                if child.tag in {"rehearsal", "metronome"}:
                    wanted = True
                elif child.tag == "words" and (
                    looks_like_a_tempo(child.text) or looks_like_a_rehearsal_mark(child.text)
                ):
                    wanted = True
            if not wanted:
                continue
            copied = copy.deepcopy(direction)
            copied.set("placement", "above")
            attributes = target_measures[index].find("attributes")
            at = list(target_measures[index]).index(attributes) + 1 if attributes is not None else 0
            target_measures[index].insert(at, copied)
            grafted += 1
    return grafted


def add_rehearsal_marks(tree: ET.ElementTree, marks: list[tuple[int, str]]) -> int:
    """Put rehearsal marks into a page's part, given (measure index, text)."""
    part = tree.getroot().find("part")
    if part is None:
        return 0
    measures = part.findall("measure")
    added = 0
    for index, text in marks:
        if not text or index >= len(measures):
            continue
        measure = measures[index]
        if any(r.text == text for r in measure.iter("rehearsal")):
            continue
        direction = ET.Element("direction")
        direction.set("placement", "above")
        kind = ET.SubElement(direction, "direction-type")
        rehearsal = ET.SubElement(kind, "rehearsal")
        rehearsal.set("enclosure", "rectangle")
        rehearsal.text = text
        attributes = measure.find("attributes")
        at = list(measure).index(attributes) + 1 if attributes is not None else 0
        measure.insert(at, direction)
        added += 1
    return added


def set_titles(tree: ET.ElementTree, title: str = "", part_name: str = "",
               composer: str = "", part_abbreviation: str | None = "") -> ET.ElementTree:
    """Put the titling into the MusicXML, where musicxml2ly will find it.

    Patching LilyPond's \header afterwards does not work: musicxml2ly builds
    one from the score's own work-title and creator and overwrites whatever was
    there.
    """
    root = tree.getroot()
    if title:
        work = root.find("work")
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        node = work.find("work-title")
        if node is None:
            node = ET.SubElement(work, "work-title")
        node.text = title
        # musicxml2ly prints the movement title as a subtitle under the title.
        # Audiveris fills it in with whatever it read largest on the page,
        # which for a score page is the title again — so the fresh part came
        # out with its name printed twice, one line under the other.
        for movement in root.findall("movement-title"):
            if (movement.text or "").strip() == title.strip():
                root.remove(movement)
    if composer:
        ident = root.find("identification")
        if ident is None:
            ident = ET.Element("identification")
            root.insert(1, ident)
        for creator in ident.findall("creator"):
            if creator.get("type") == "composer":
                creator.text = composer
                break
        else:
            node = ET.SubElement(ident, "creator")
            node.set("type", "composer")
            node.text = composer
    if part_name:
        for tag in (".//part-name", ".//instrument-name"):
            for node in root.findall(tag):
                node.text = part_name
        # The abbreviation is what musicxml2ly writes down the left margin of
        # every system after the first, and Audiveris fills it in from the
        # score's own staff label — a percussion part came out abbreviated
        # "Timpani".  Unless the caller asks for one, take it out.
        if part_abbreviation is not None:
            for node in root.findall(".//part-abbreviation"):
                node.text = part_abbreviation
    return tree


def sanitize(tree: ET.ElementTree) -> list[str]:
    """Repair the MusicXML quirks that stop an engraver dead.

    OMR output is machine-written and does not always obey the pairing rules a
    human editor would.  `musicxml2ly` trusts it and crashes rather than
    complaining — a tuplet that stops without having started leaves an index
    unset and it dies in `group_tuplets` with a TypeError, taking the whole
    engraving with it.

    Only *structural* repairs belong here: nothing that changes which notes are
    played.  Each repair is returned as a line so the run can report what it had
    to patch.
    """
    notes: list[str] = []
    part = tree.getroot().find("part")
    if part is None:
        return notes

    # `divisions` of 0 is meaningless, and it is fatal twice over: the
    # validator divides by it, and so does musicxml2ly, which dies with a
    # ZeroDivisionError deep inside LilyPond's own MusicXML reader and takes
    # the whole engraving with it.  Audiveris emits it on a page it could not
    # make sense of.  Replace it with whatever the rest of the document uses.
    declared = [
        int(node.text) for node in part.iter("divisions")
        if node.text and node.text.strip().lstrip("-").isdigit() and int(node.text) > 0
    ]
    fallback = collections.Counter(declared).most_common(1)[0][0] if declared else 1
    for measure in part.findall("measure"):
        for attributes in measure.findall("attributes"):
            for node in attributes.findall("divisions"):
                value = int(node.text) if node.text and node.text.strip().lstrip("-").isdigit() else 0
                if value <= 0:
                    node.text = str(fallback)
                    notes.append(
                        f"measure {measure.get('number')}: divisions was {value}, "
                        f"set to {fallback}"
                    )

    # A whole-bar rest whose duration is not a bar.  Audiveris writes 36 where
    # the bar is 24 on 58 of this part's 269 bar rests, and the consequence is
    # invisible in the notes and obvious on the page: LilyPond lays that bar out
    # one and a half bars wide, so every following bar in the system is shoved
    # sideways and the part looks mis-barred when the music underneath is right.
    # `measure="yes"` already means "one bar, whatever the number says", so
    # making the number agree changes nothing but the engraving.
    div, beats, beat_type = 1, 4, 4
    for measure in part.findall("measure"):
        attributes = measure.find("attributes")
        if attributes is not None:
            declared = attributes.findtext("divisions")
            if declared and declared.strip().isdigit() and int(declared) > 0:
                div = int(declared)
            time = attributes.find("time")
            if time is not None:
                if (time.findtext("beats") or "").isdigit():
                    beats = int(time.findtext("beats"))
                if (time.findtext("beat-type") or "").isdigit():
                    beat_type = int(time.findtext("beat-type"))
        want = Fraction(div * 4 * beats, beat_type)
        if want.denominator != 1:
            continue
        for note in measure.findall("note"):
            rest = note.find("rest")
            if rest is None or rest.get("measure") != "yes":
                continue
            duration = note.find("duration")
            if duration is None:
                duration = ET.SubElement(note, "duration")
                duration.text = str(int(want))
                notes.append(f"measure {measure.get('number')}: bar rest had no duration")
            elif duration.text != str(int(want)):
                notes.append(
                    f"measure {measure.get('number')}: bar rest lasted "
                    f"{duration.text} where the bar is {int(want)}"
                )
                duration.text = str(int(want))

    # A note with neither a <type> nor a positive <duration> cannot be
    # engraved, and LilyPond does not say so politely: its own error path
    # references an undefined variable and dies with a NameError inside
    # musicxml.py.  Drop the note and say which bar lost it.
    for measure in part.findall("measure"):
        for note in list(measure.findall("note")):
            duration = note.findtext("duration")
            positive = duration is not None and duration.strip().lstrip("-").isdigit() \
                and int(duration) > 0
            if note.find("type") is None and not positive:
                measure.remove(note)
                notes.append(
                    f"measure {measure.get('number')}: dropped a note with no "
                    f"duration and no type"
                )

    open_tuplets: dict[tuple[str, str], ET.Element] = {}
    for measure in part.findall("measure"):
        for note in measure.findall("note"):
            voice = note.findtext("voice") or "1"
            for notations in note.findall("notations"):
                for tuplet in list(notations.findall("tuplet")):
                    number = tuplet.get("number", "1")
                    key = (voice, number)
                    kind = tuplet.get("type")
                    if kind == "start":
                        if key in open_tuplets:
                            notations.remove(tuplet)
                            notes.append(
                                f"measure {measure.get('number')}: tuplet {number} "
                                f"started twice in voice {voice}"
                            )
                        else:
                            open_tuplets[key] = tuplet
                    elif kind == "stop":
                        if key not in open_tuplets:
                            notations.remove(tuplet)
                            notes.append(
                                f"measure {measure.get('number')}: tuplet {number} "
                                f"stopped without starting in voice {voice}"
                            )
                        else:
                            del open_tuplets[key]
    for (voice, number), tuplet in open_tuplets.items():
        for notations in part.iter("notations"):
            if tuplet in list(notations):
                notations.remove(tuplet)
                notes.append(f"tuplet {number} in voice {voice} never stopped")
    return notes


def smooth_seams(tree: ET.ElementTree) -> list[str]:
    """Make 27 pages of a score read as one part.

    Two things come along with the pages and do not belong in a part:

    * **The score's own page and system breaks.**  MusicXML carries them as
      `<print new-system="yes">`, musicxml2ly turns them into `\break`, and a
      break stops LilyPond merging whole-bar rests across it.  The publisher's
      Timpani part shows a seven-bar multi-rest where this showed "2" then "5"
      — the run was split at the score's page boundary, which the player has no
      reason to care about.
    * **The clef, key, metre, divisions and staff details restated on every
      page.**  Each page begins by declaring them, correctly, because each page
      is its own document.  Joined end to end that is twenty-seven redundant
      clef changes down the part — and worse, an `<attributes>` element in the
      middle of a run of empty bars stops musicxml2ly merging them, which is
      what split a seven-bar rest into "2" and "5".

    Both are removed by comparing against what is already in force, so a real
    change — a clef change, a change of metre — still comes through.
    """
    notes: list[str] = []
    part = tree.getroot().find("part")
    if part is None:
        return notes

    breaks = 0
    for measure in part.findall("measure"):
        for element in list(measure.findall("print")):
            measure.remove(element)
            breaks += 1
    if breaks:
        notes.append(f"removed {breaks} page/system break(s) inherited from the score")

    state: dict[str, str] = {}
    dropped = 0
    for index, measure in enumerate(part.findall("measure")):
        attributes = measure.find("attributes")
        if attributes is None:
            continue
        for child in list(attributes):
            # `divisions` and `staff-details` are restated on every page too,
            # and they matter as much as the clef: musicxml2ly treats *any*
            # <attributes> mid-run as a reason to end a multi-measure rest, so
            # one redundant `<divisions>6</divisions>` is what turned the
            # publisher's seven-bar rest into "2" and "5".
            if child.tag not in {"clef", "key", "time", "divisions", "staff-details"}:
                continue
            signature = ET.tostring(child, encoding="unicode")
            signature = " ".join(signature.split())
            key = child.tag + (child.get("number") or "")
            if index > 0 and state.get(key) == signature:
                attributes.remove(child)
                dropped += 1
            else:
                state[key] = signature
        if len(attributes) == 0:
            measure.remove(attributes)
    if dropped:
        notes.append(f"removed {dropped} restatement(s) of a clef, key or time signature")
    return notes


def measure_length(measure: ET.Element) -> int:
    """How long a measure actually is, in divisions.

    A bar with two voices is not the sum of its notes.  MusicXML writes the
    second voice by stepping the cursor *back* with `<backup>` and laying it
    down again, so adding up every `<duration>` counts the bar twice — which is
    exactly what happened on the percussion part, where 73 bars carry two
    voices and every one of them was reported as "does not add up".

    Walk the cursor instead, and the bar is how far it ever reached.
    """
    cursor = 0
    longest = 0
    for element in measure:
        if element.tag == "note":
            if element.find("chord") is not None:
                continue  # a chord sounds with the note before it
            duration = element.findtext("duration")
            if duration and duration.strip().lstrip("-").isdigit():
                cursor += int(duration)
                longest = max(longest, cursor)
        elif element.tag == "backup":
            duration = element.findtext("duration")
            if duration and duration.strip().isdigit():
                cursor -= int(duration)
        elif element.tag == "forward":
            duration = element.findtext("duration")
            if duration and duration.strip().isdigit():
                cursor += int(duration)
                longest = max(longest, cursor)
    return longest


@dataclass
class Repair:
    """One structural change, and whether it was a guess.

    A repair that only rearranges the file (a redundant clef, a barline's
    duration) is bookkeeping.  A repair that *invents* music — filling an empty
    bar, padding a short one — is a guess, and a guess has to stay visible: it
    is flagged, it keeps the run untrustworthy, and it names the bar so somebody
    can look at it.
    """

    text: str
    measure: int | None = None
    guess: bool = False

    def __str__(self) -> str:  # so a caller can keep treating these as lines
        return self.text


def fill_incomplete(tree: ET.ElementTree) -> list[Repair]:
    """Make every bar last a bar, and say where music had to be invented.

    An empty bar and a bar half a beat short are both engraving hazards: the
    first collapses to nothing, the second pushes everything after it sideways.
    Neither can be left, and neither can be repaired honestly — the notes that
    should be there were not read.  So they are filled with rests and reported
    as guesses.
    """
    out: list[Repair] = []
    part = tree.getroot().find("part")
    if part is None:
        return out
    div, beats, beat_type = 1, 4, 4
    for measure in part.findall("measure"):
        attributes = measure.find("attributes")
        if attributes is not None:
            declared = attributes.findtext("divisions")
            if declared and declared.strip().isdigit() and int(declared) > 0:
                div = int(declared)
            time = attributes.find("time")
            if time is not None:
                if (time.findtext("beats") or "").isdigit():
                    beats = int(time.findtext("beats"))
                if (time.findtext("beat-type") or "").isdigit():
                    beat_type = int(time.findtext("beat-type"))
        want = Fraction(div * 4 * beats, beat_type)
        if want.denominator != 1:
            continue
        want = int(want)
        number = int(measure.get("number") or 0)

        notes = [n for n in measure.findall("note") if n.find("chord") is None]
        if any(n.find("rest") is not None and n.find("rest").get("measure") == "yes"
               for n in notes):
            continue
        total = measure_length(measure)

        if total == 0 and not notes:
            note = ET.SubElement(measure, "note")
            rest = ET.SubElement(note, "rest")
            rest.set("measure", "yes")
            ET.SubElement(note, "duration").text = str(want)
            out.append(Repair(f"measure {number}: nothing was read; filled with a bar's rest",
                              measure=number, guess=True))
        elif 0 < total < want:
            note = ET.SubElement(measure, "note")
            ET.SubElement(note, "rest")
            ET.SubElement(note, "duration").text = str(want - total)
            out.append(Repair(
                f"measure {number}: short by {Fraction(want - total, want)} of a bar; "
                f"padded with a rest", measure=number, guess=True))
    return out


@dataclass
class MeasureCheck:
    number: int
    beats: Fraction  # what the notes add up to, in whole notes
    expected: Fraction  # what the time signature asks for
    notes: int

    @property
    def ok(self) -> bool:
        return self.beats == self.expected


def check(tree: ET.ElementTree) -> list[MeasureCheck]:
    """Add up every measure and compare it with the time signature in force."""
    part = tree.getroot().find("part")
    if part is None:
        return []
    divisions = 1
    expected = Fraction(1)  # a whole note until told otherwise
    out: list[MeasureCheck] = []

    for measure in part.findall("measure"):
        attributes = measure.find("attributes")
        if attributes is not None:
            div = attributes.findtext("divisions")
            # OMR output has been seen to declare `divisions` of 0, which is
            # meaningless and used to take the validator down with a
            # ZeroDivisionError.  Keep the last sane value instead.
            if div and int(div) > 0:
                divisions = int(div)
            time = attributes.find("time")
            if time is not None:
                beats = time.findtext("beats")
                beat_type = time.findtext("beat-type")
                if beats and beat_type:
                    expected = Fraction(int(beats), int(beat_type))

        counted = sum(1 for n in measure.findall("note") if n.find("chord") is None)
        whole_bar_rest = any(
            n.find("rest") is not None and n.find("rest").get("measure") == "yes"
            for n in measure.findall("note")
        )
        if whole_bar_rest:
            # A bar's rest, or a multi-bar rest — one written measure whatever
            # its duration says, which is how it is counted in the scan too.
            total = expected
        else:
            total = Fraction(measure_length(measure), divisions * 4)
        out.append(
            MeasureCheck(
                number=int(measure.get("number", len(out) + 1)),
                beats=total, expected=expected, notes=counted,
            )
        )
    return out


def count_measures(tree: ET.ElementTree) -> int:
    part = tree.getroot().find("part")
    return len(part.findall("measure")) if part is not None else 0


def systems_of(tree: ET.ElementTree) -> list[tuple[int, int]]:
    """Where each system starts and ends, as measure indices [start, end).

    Audiveris marks a system break with `<print new-system="yes">` on the first
    measure of the new system, which is how a page's recognised measures can be
    lined up with the systems a human sees on that page.  `smooth_seams` throws
    these away later, on purpose — they are the *scan's* layout, not the fresh
    part's — so anything that needs them has to ask before that happens.
    """
    part = tree.getroot().find("part")
    if part is None:
        return []
    measures = part.findall("measure")
    starts = [0]
    for index, measure in enumerate(measures):
        if index == 0:
            continue
        printing = measure.find("print")
        if printing is not None and printing.get("new-system") == "yes":
            starts.append(index)
    return [(a, b) for a, b in zip(starts, starts[1:] + [len(measures)])]


def multi_rests_in(tree: ET.ElementTree, span: tuple[int, int]) -> list[tuple[int, int]]:
    """(measure index, count) for every multi-measure rest inside one system."""
    part = tree.getroot().find("part")
    if part is None:
        return []
    measures = part.findall("measure")
    out: list[tuple[int, int]] = []
    for index in range(span[0], min(span[1], len(measures))):
        element = measures[index].find(".//multiple-rest")
        if element is not None and (element.text or "").strip().isdigit():
            out.append((index, int(element.text.strip())))
    return out


def set_multi_rest(tree: ET.ElementTree, index: int, count: int) -> int:
    """Make the multi-measure rest at `index` last `count` bars.

    Audiveris writes a multi-measure rest out *expanded*: the first measure
    carries `<multiple-rest>7</multiple-rest>` and six more empty measures
    follow it.  So changing the count means changing the number and adding or
    removing that many measures — and the measures to copy are right there, so
    the added ones are real bar rests in the right metre rather than something
    invented.

    Returns how many measures were added (negative if removed).
    """
    part = tree.getroot().find("part")
    if part is None:
        return 0
    measures = part.findall("measure")
    if not 0 <= index < len(measures):
        return 0
    element = measures[index].find(".//multiple-rest")
    if element is None:
        return 0
    was = int((element.text or "0").strip() or 0)
    if count == was or count < 1:
        return 0
    element.text = str(count)
    change = count - was
    children = list(part)
    at = children.index(measures[index])
    if change > 0:
        template = measures[index + 1] if index + 1 < len(measures) else measures[index]
        for step in range(change):
            copy = _copy_bar_rest(template)
            part.insert(at + was + step, copy)
    else:
        for _ in range(-change):
            victim = at + count
            if victim + 1 < len(list(part)):
                part.remove(list(part)[victim])
    _renumber(part)
    return change


def _copy_bar_rest(template: ET.Element) -> ET.Element:
    """A fresh empty measure modelled on one of the rest's own bars.

    Nothing but the rest survives.  Leaving an empty `<measure-style/>` behind
    was enough to end the multi-measure rest as far as musicxml2ly is
    concerned, so a twenty-four bar rest came out as twenty-four empty bars
    with barlines between them — which is not what a player counts from.
    """
    copy = ET.fromstring(ET.tostring(template))
    for tag in ("print", "barline", "attributes", "direction"):
        for child in list(copy.findall(tag)):
            copy.remove(child)
    return copy


def _renumber(part: ET.Element) -> None:
    for number, measure in enumerate(part.findall("measure"), start=1):
        measure.set("number", str(number))


def show_bar_rests(tree: ET.ElementTree) -> int:
    """Let the whole-bar rests be seen.

    Audiveris marks every measure of a multi-measure rest `print-object="no"`,
    because on the page they are not drawn — the thick bar and its number stand
    for all of them.  musicxml2ly takes that literally and writes a *spacer*,
    so the fresh part shows sixteen empty bars where the original shows one bar
    marked 16.  With the attribute gone it writes `R1*16`, which is the
    multi-measure rest, drawn and numbered, and which is also what MuseScore
    and Sibelius expect to find.

    Only whole-bar rests are touched, and nothing that sounds is changed.
    """
    changed = 0
    for note in tree.getroot().iter("note"):
        rest = note.find("rest")
        if rest is None or rest.get("measure") != "yes":
            continue
        if note.get("print-object") == "no":
            del note.attrib["print-object"]
            changed += 1
    return changed


def written_bars(tree: ET.ElementTree, span: tuple[int, int]) -> list[tuple[int, int | None]]:
    """The bars a system *prints*, and how long each one lasts.

    Audiveris writes a multi-measure rest out expanded — one measure carrying
    the count and then that many silent measures behind it — so the recognised
    measures inside a system do not line up one for one with the bars on the
    page.  Walking the span and stepping over each rest's own measures gives
    the printed bars back, which is the sequence a page can be compared with.
    """
    part = tree.getroot().find("part")
    if part is None:
        return []
    measures = part.findall("measure")
    out: list[tuple[int, int | None]] = []
    index = span[0]
    while index < min(span[1], len(measures)):
        element = measures[index].find(".//multiple-rest")
        count = None
        if element is not None and (element.text or "").strip().isdigit():
            count = int(element.text.strip())
        out.append((index, count))
        index += max(1, count or 1)
    return out


def make_multi_rest(tree: ET.ElementTree, index: int, count: int) -> int:
    """Turn one measure into a multi-measure rest of `count` bars.

    Used when the page plainly shows the thick bar and the engine read the bar
    as music instead.  Nothing is invented by doing this: a multi-measure rest
    has no content beyond its length, so the page's number is the whole of it.
    """
    part = tree.getroot().find("part")
    if part is None:
        return 0
    measures = part.findall("measure")
    if not 0 <= index < len(measures) or count < 1:
        return 0
    measure = measures[index]
    keep = [child for child in measure
            if child.tag in {"print", "attributes", "direction"}]
    for child in list(measure):
        measure.remove(child)
    for child in keep:
        measure.append(child)
    attributes = measure.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        measure.insert(1 if measure.find("print") is not None else 0, attributes)
    for style in list(attributes.findall("measure-style")):
        attributes.remove(style)
    style = ET.SubElement(attributes, "measure-style")
    ET.SubElement(style, "multiple-rest").text = str(count)
    note = ET.SubElement(measure, "note")
    note.set("print-object", "no")
    rest = ET.SubElement(note, "rest")
    rest.set("measure", "yes")
    ET.SubElement(note, "duration").text = str(_divisions_before(part, index) or 4)
    at = list(part).index(measure)
    for step in range(count - 1):
        part.insert(at + 1 + step, _copy_bar_rest(measure))
    _renumber(part)
    return count - 1


def _divisions_before(part: ET.Element, index: int) -> int:
    """A whole bar's worth of divisions, as the part has said so far."""
    divisions, beats, beat_type = 0, 4, 4
    for number, measure in enumerate(part.findall("measure")):
        if number > index:
            break
        for attributes in measure.findall("attributes"):
            text = attributes.findtext("divisions")
            if text and text.strip().isdigit():
                divisions = int(text.strip())
            time = attributes.find("time")
            if time is not None:
                if (time.findtext("beats") or "").strip().isdigit():
                    beats = int(time.findtext("beats").strip())
                if (time.findtext("beat-type") or "").strip().isdigit():
                    beat_type = int(time.findtext("beat-type").strip())
    if not divisions:
        return 0
    return int(divisions * 4 * beats / beat_type)


def pad_system(tree: ET.ElementTree, span: tuple[int, int], extra: int) -> int:
    """Add `extra` empty bars at the end of a system.

    The last resort, and it exists because of what a part is for.  When the
    printed bar numbers say a system holds ten bars and only seven were read,
    the three that are missing cannot be recovered — but leaving them out is
    worse than marking them, because every bar number after that point is then
    wrong, and a part whose numbers do not match the conductor's score cannot
    be used at a rehearsal at all.  So the bars are put in as rests and
    reported, and the player checks three bars against the original instead of
    counting the whole piece again.
    """
    part = tree.getroot().find("part")
    if part is None or extra < 1:
        return 0
    measures = part.findall("measure")
    last = min(span[1], len(measures)) - 1
    if last < 0:
        return 0
    template = measures[last]
    at = list(part).index(template)
    for step in range(extra):
        part.insert(at + 1 + step, _blank_bar(template, _divisions_before(part, last)))
    _renumber(part)
    return extra


def _blank_bar(template: ET.Element, duration: int) -> ET.Element:
    measure = ET.Element("measure")
    note = ET.SubElement(measure, "note")
    note.set("print-object", "no")
    rest = ET.SubElement(note, "rest")
    rest.set("measure", "yes")
    ET.SubElement(note, "duration").text = str(duration or 4)
    return measure


def strip_stray_lyrics(tree: ET.ElementTree, dense: float = 0.10) -> list[str]:
    """Throw away words that are printing on the page, not words to sing.

    Audiveris ran the text step over the bottom of a timpani part and attached
    the publisher's imprint to four notes as lyrics; musicxml2ly then gave the
    part a Lyrics context, and the fresh page carried "VERLAG AG, 4537
    Wicdlisbach," across the staff over bar 211, with a stanza mark "1." beside
    the first bar.

    A song is not distinguished from that by what the words say — it is
    distinguished by how many notes have one.  Below one note in ten, the words
    are furniture; a real vocal line has one on nearly every note.  A part with
    genuine lyrics keeps them, and either way the count is reported.
    """
    notes = list(tree.getroot().iter("note"))
    with_words = [n for n in notes if n.find("lyric") is not None]
    if not with_words:
        return []
    if len(with_words) >= dense * max(1, len(notes)):
        return [f"{len(with_words)} note(s) carry lyrics; kept"]
    words = []
    for note in with_words:
        for lyric in list(note.findall("lyric")):
            words.append((lyric.findtext("text") or "").strip())
            note.remove(lyric)
    shown = " ".join(w for w in words if w)[:60]
    return [f"dropped {len(with_words)} stray lyric(s) — {shown!r} — "
            f"printing on the page, not words to sing"]


def dedupe_directions(tree: ET.ElementTree) -> int:
    """One tempo marking per bar, not the same one twice.

    A part can carry a marking of its own and be given the same one again by
    the graft from the score's top staff, and "Presto" printed over "Presto" is
    the visible result.
    """
    removed = 0
    for measure in tree.getroot().iter("measure"):
        seen: set[str] = set()
        for direction in list(measure.findall("direction")):
            text = " ".join(
                (w.text or "").strip() for w in direction.iter("words")
            ).strip()
            if not text:
                continue
            if text in seen:
                measure.remove(direction)
                removed += 1
            else:
                seen.add(text)
    return removed


# Note values LilyPond can write, longest first, as multiples of a quarter.
_VALUES = [
    ("breve", 8.0), ("whole", 4.0), ("half", 2.0), ("quarter", 1.0),
    ("eighth", 0.5), ("16th", 0.25), ("32nd", 0.125), ("64th", 0.0625),
]


def name_durations(tree: ET.ElementTree) -> list[str]:
    """Give every note a written value, and shorten the ones that have none.

    A rest can reach the MusicXML with a duration and no `<type>`: Audiveris
    knows how long the gap is without deciding what rest to draw in it.
    musicxml2ly then has nothing to print and dies part-way through the file
    with `'NoneType' object has no attribute 'print_ly'` — LilyPond's own error
    path, so the message says nothing about the note that caused it, and the
    .ly it leaves behind is truncated in the middle of a bar.  Two of the ten
    fleet cases failed exactly this way.

    Most of them are simply unnamed: 6 against 12 divisions is an eighth, 18 is
    a dotted quarter.  A few are lengths no single rest can be — 20 against 12
    is five sixths of a bar — and those are cut to the longest value that fits
    and reported.  `fill_incomplete` then pads the bar out, so the bar still
    adds up and the change is visible in two places rather than none.
    """
    notes: list[str] = []
    part = tree.getroot().find("part")
    if part is None:
        return notes
    divisions = 0
    shortened = 0
    named = 0
    for measure in part.findall("measure"):
        for attributes in measure.findall("attributes"):
            text = attributes.findtext("divisions")
            if text and text.strip().isdigit() and int(text.strip()):
                divisions = int(text.strip())
        if not divisions:
            continue
        for note in measure.findall("note"):
            if note.find("type") is not None or note.find("grace") is not None:
                continue
            rest = note.find("rest")
            if rest is not None and rest.get("measure") == "yes":
                continue                      # a whole-bar rest needs no value
            text = note.findtext("duration")
            if not text or not text.strip().lstrip("-").isdigit():
                continue
            quarters = int(text.strip()) / divisions
            name, dots, value = _nearest_value(quarters)
            if name is None:
                continue
            if abs(value - quarters) > 1e-6:
                note.find("duration").text = str(int(round(value * divisions)))
                shortened += 1
            _write_type(note, name, dots)
            named += 1
    if named:
        notes.append(f"{named} note(s) or rest(s) had a length but no written value; "
                     f"named from the length")
    if shortened:
        notes.append(f"{shortened} of them were a length no single note can be, and "
                     f"were cut to the longest that fits — the bar is padded and flagged")
    return notes


def _nearest_value(quarters: float) -> tuple[str | None, int, float]:
    """The longest (name, dots) worth no more than `quarters`."""
    if quarters <= 0:
        return None, 0, 0.0
    best: tuple[str | None, int, float] = (None, 0, 0.0)
    for name, base in _VALUES:
        for dots in (0, 1, 2):
            value = base * (2 - 0.5 ** dots)
            if value <= quarters + 1e-6 and value > best[2]:
                best = (name, dots, value)
    return best


def _write_type(note: ET.Element, name: str, dots: int) -> None:
    """Put `<type>` and its dots where MusicXML says they belong."""
    after = {"duration", "tie", "instrument", "voice", "rest", "pitch",
             "unpitched", "chord", "grace", "cue"}
    at = 0
    for index, child in enumerate(note):
        if child.tag in after:
            at = index + 1
    element = ET.Element("type")
    element.text = name
    note.insert(at, element)
    for step in range(dots):
        note.insert(at + 1 + step, ET.Element("dot"))


def tame_text(tree: ET.ElementTree) -> list[str]:
    """Take out the characters that break the engraver.

    Everything readable on the page arrives here through OCR, and OCR of a
    smudged tempo marking produces things no engraver expects.  One word on a
    crooked photocopy came back as `A"egro m0 to al ways`, and musicxml2ly
    writes text straight into a LilyPond string: the stray double quote closed
    it, and LilyPond died with "EOF found inside string" three hundred lines
    later, at the end of the file, saying nothing about the bar it came from.

    A double quote becomes a single one and a backslash is dropped, everywhere
    in the document.  Neither can be meant: a backslash is not a character in
    music, and a title with a quotation mark in it reads the same with an
    apostrophe.
    """
    changed = 0
    for element in tree.getroot().iter():
        for attribute in ("text", "tail"):
            value = getattr(element, attribute)
            if not value or ('"' not in value and "\\" not in value):
                continue
            setattr(element, attribute, value.replace('"', "'").replace("\\", ""))
            changed += 1
    return ([f"{changed} piece(s) of text held a quote or a backslash, which "
             f"LilyPond reads as syntax; taken out"] if changed else [])
