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
        # A bar's rest lasts a bar, whatever length was written on it, and a
        # bar holding one is not therefore beyond repair: on four of the fleet
        # a whole-bar rest sat in one voice while another voice overran, and
        # skipping the bar for the rest's sake left the overrun in place.
        for note in notes:
            rest = note.find("rest")
            if rest is not None and rest.get("measure") == "yes":
                length = note.find("duration")
                if length is not None and _duration_of(note) != want:
                    length.text = str(want)
        _mend_missing_backups(measure, want)
        _mend_the_cursor(measure)
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
            # And say what rest it is.  A rest with a length and no written
            # value is what musicxml2ly dies on, and a bar filled here without
            # one puts the crash straight back — which is exactly what happened
            # once the naming pass ran before this one instead of after it.
            _name_one(note, (want - total) / max(1, div))
            out.append(Repair(
                f"measure {number}: short by {Fraction(want - total, want)} of a bar; "
                f"padded with a rest", measure=number, guess=True))
        elif total > want:
            out.extend(_trim_overfull(measure, number, want, div))
    return out


def _trim_overfull(measure: ET.Element, number: int, want: int,
                   divisions: int) -> list["Repair"]:
    """Take a bar that is too long back down to its bar's length.

    A bar that is *short* is a nuisance; a bar that is **long** poisons
    everything after it.  LilyPond keeps counting from where the music
    actually got to, so one extra sixteenth in bar 229 puts every later bar a
    sixteenth off the barline grid — and a multi-measure rest that does not
    start on a barline can neither be collapsed nor broken across a system.
    Measured on a timpani part, one stray sixteenth rest made the last system
    915 pt wide on a 595 pt page: the music simply ran off the paper, from bar
    237 to the end.

    **The overflow belongs to one voice**, which is why this looks inside
    them.  The first version refused any bar holding a `<backup>` and so
    repaired nothing at all on a percussion part, where 61 bars have two
    voices: bar 36 was a quarter too long in voice one, whose four notes are
    all rests, and bar 72 five quarters too long in voice two, whose last two
    are.  A voice that is too *short* needs nothing done to it — measured,
    musicxml2ly pads one with a skip of its own accord, so `e4 e4 e4` in a 4/4
    bar comes out as `e4 e4 e4 s4` and the bar check passes.

    Four passes, least damaging first: the `<forward>` gaps written before the
    voice comes in, then its trailing rests, then any other rest in it, and
    only then — and only for a small overrun — the notes at its end.  That
    last one is a real change to the music and is reported as one.  It is
    still the better answer than leaving a small overrun: the alternative is
    not "the bar as written" but every bar after it off the grid, which is the
    fault that was reported as "a complete mess from bar 237".
    """
    out: list[Repair] = []
    _mend_the_cursor(measure)   # before measuring: an overshooting backup hides
    spans, order, gaps = _voice_spans(measure)   # a voice behind the barline
    gone: set[int] = set()
    for voice in sorted(spans):
        excess = spans[voice] - want
        if excess <= 0:
            continue
        was_over, taken, hurt = excess, 0, 0
        notes = [n for n in order[voice] if n.find("chord") is None]

        def give(note: ET.Element) -> None:
            nonlocal excess, taken, hurt
            before = excess
            excess, taken = _give_back(measure, note, excess, taken,
                                       divisions, gone)
            if note.tag == "note" and note.find("rest") is None:
                hurt += before - excess

        trailing: list[ET.Element] = []
        for note in reversed(notes):
            if note.find("rest") is None:
                break
            trailing.append(note)
        rests = [n for n in reversed(notes) if n.find("rest") is not None]
        def spend(wave: list[ET.Element]) -> None:
            for note in wave:               # one rest worth exactly the excess
                if excess and id(note) not in gone and _duration_of(note) == excess:
                    give(note)
                    break
            for note in wave:
                if excess <= 0:
                    break
                if id(note) not in gone:
                    give(note)

        for wave in (gaps.get(voice, [])[::-1], trailing, rests):
            spend(wave)
        # What is left has to come out of written notes, and that is only
        # done for an overrun of **half a bar or less**.  Bigger than that and
        # the fault is much more likely to be the time signature than the
        # notes: measured across the fleet, the voices that overrun by more
        # are on pages where Audiveris printed no `<time>` of its own and the
        # previous page's carried over — one of them is a bar of five quarters
        # declared 3/8, and another is 138 divisions in a bar of 48.  Deleting
        # most of the music to fit a meter that is itself misread is the worse
        # answer of the two, so those bars are left long and said so.
        #
        # Half, not a quarter: bar 7 of one part is an eighth, an eighth and a
        # half-note in a 2/4 bar, where the half is plainly a misread quarter.
        # The excess is exactly half a bar, and a quarter-bar line refused the
        # one change that bar needs.
        too_much = excess * 2 > want
        if not too_much:
            spend(notes[::-1])

        where = (f"measure {number}: voice {voice} was "
                 f"{Fraction(was_over, want)} of a bar too long")
        if excess and too_much:
            out.append(Repair(
                where + "; that is too much of it to be a misread note, so "
                "the time signature is the more likely fault and the music "
                "was left as it was — every later bar sits off the barline",
                measure=number, guess=False))
        elif excess:
            out.append(Repair(
                where + "; nothing in it could be shortened, so every later "
                "bar sits off the barline", measure=number, guess=False))
        elif hurt:
            out.append(Repair(
                where + f"; {Fraction(was_over - hurt, want)} of rest and "
                f"{Fraction(hurt, want)} of *written notes* were taken out to "
                "put the barline back", measure=number, guess=True))
        else:
            out.append(Repair(
                where + f"; {Fraction(taken, want)} of rest was taken out",
                measure=number, guess=True))
    _mend_the_cursor(measure)
    return out


def _mend_missing_backups(measure: ET.Element, want: int) -> bool:
    """Put back a `<backup>` Audiveris left out between two voices.

    MusicXML lays a second voice down by stepping the cursor back to the
    barline first, and Audiveris usually writes that backup — but not always.
    Bar 182 of one part is two whole-bar rests, one per voice, written one
    after the other with nothing between them, so the second reads as starting
    on beat five and the bar is twice its length.  LilyPond then loses the
    barline for good.

    The repair is only made when it is provably the right one: the bar must be
    too long as written, the missing backups must be at the point where a
    voice that has not sounded yet begins, and putting them in must bring the
    bar back to its length.  A bar where two voices genuinely take turns —
    voice one for two beats, voice two for the next two — is not too long, so
    it is never touched.
    """
    if measure_length(measure) <= want:
        return False
    cursor = 0
    seen: set[str] = set()
    current: str | None = None
    marks: list[tuple[int, int]] = []
    for index, element in enumerate(measure):
        if element.tag == "note":
            voice = element.findtext("voice") or "1"
            if voice != current:
                if voice not in seen and cursor > 0:
                    marks.append((index, cursor))
                    cursor = 0
                current = voice
                seen.add(voice)
            if element.find("chord") is None:
                cursor += _duration_of(element)
        elif element.tag == "backup":
            cursor -= _duration_of(element)
            current = None
        elif element.tag == "forward":
            cursor += _duration_of(element)
    if not marks:
        return False
    trial = copy.deepcopy(measure)
    for index, back in reversed(marks):
        trial.insert(index, _backup(back))
    if measure_length(trial) > want:
        return False
    for index, back in reversed(marks):
        measure.insert(index, _backup(back))
    return True


def _backup(duration: int) -> ET.Element:
    element = ET.Element("backup")
    ET.SubElement(element, "duration").text = str(duration)
    return element


def _voice_spans(measure: ET.Element) -> tuple[dict[str, int],
                                              dict[str, list[ET.Element]],
                                              dict[str, list[ET.Element]]]:
    """How far each voice reaches, its notes, and the gaps written before them.

    Walk the same cursor `measure_length` walks, so a `<backup>` puts the next
    voice back at the start of the bar instead of adding to it.  A voice's
    length is the furthest the cursor got while that voice was sounding.

    A `<forward>` is a gap — whitespace before a voice comes in — and it is
    handed back separately because it is the *least damaging* thing to shorten
    when a voice runs past the barline: taking a beat out of a gap moves a
    note, taking one out of a note deletes music.  Bar 66 of one part is a
    gap of fifty-four in a bar of forty-eight, so the note after it could
    never fit however much of the note was given up.
    """
    spans: dict[str, int] = {}
    order: dict[str, list[ET.Element]] = {}
    gaps: dict[str, list[ET.Element]] = {}
    waiting: list[ET.Element] = []
    cursor = 0
    for element in measure:
        if element.tag == "note":
            voice = element.findtext("voice") or "1"
            order.setdefault(voice, []).append(element)
            gaps.setdefault(voice, []).extend(waiting)
            waiting = []
            if element.find("chord") is not None:
                continue
            cursor += _duration_of(element)
            spans[voice] = max(spans.get(voice, 0), cursor)
        elif element.tag == "backup":
            cursor -= _duration_of(element)
            waiting = []
        elif element.tag == "forward":
            cursor += _duration_of(element)
            waiting.append(element)
    return spans, order, gaps


def _duration_of(element: ET.Element) -> int:
    text = (element.findtext("duration") or "").strip()
    return int(text) if text.lstrip("-").isdigit() else 0


def _give_back(measure: ET.Element, note: ET.Element, excess: int, taken: int,
               divisions: int, gone: set[int]) -> tuple[int, int]:
    """Drop or shorten one note, and say how much of the excess is left."""
    was = _duration_of(note)
    if was <= 0:
        return excess, taken
    if was <= excess:
        for other in _chord_with(measure, note):
            measure.remove(other)
            gone.add(id(other))
        measure.remove(note)
        gone.add(id(note))
        return excess - was, taken + was
    for part in [note, *_chord_with(measure, note)]:
        part.find("duration").text = str(was - excess)
        if part.tag != "note":
            continue                    # a <forward> is a gap; it has no value
        for tag in ("type", "dot", "time-modification"):
            for child in list(part.findall(tag)):
                part.remove(child)
        if divisions:
            _name_one(part, (was - excess) / divisions)
    return 0, taken + excess


def _chord_with(measure: ET.Element, note: ET.Element) -> list[ET.Element]:
    """The `<chord>` notes sounding with this one, so the two go together.

    Drop the head of a chord on its own and the notes below it become a chord
    with nothing to attach to, which is a different bar again.
    """
    children = list(measure)
    try:
        at = children.index(note)
    except ValueError:
        return []
    out: list[ET.Element] = []
    for element in children[at + 1:]:
        if element.tag != "note" or element.find("chord") is None:
            break
        out.append(element)
    return out


def _mend_the_cursor(measure: ET.Element) -> None:
    """Stop a `<backup>` from stepping back past the start of the bar.

    A backup usually returns the cursor to nought before the next voice, and
    once a voice has been shortened its backup is too long by the same amount:
    left alone it would start the next voice *before* the barline.  It happens
    without any shortening too — Audiveris writes the same backup after every
    voice of a bar, sized for the longest, so the shorter ones step back too
    far as written.

    Only an overshoot is corrected, never a backup that lands inside the bar:
    a voice that genuinely comes in on beat three is written exactly that way,
    and rewriting its backup would move it.  A cursor below nought is not a
    reading of the music at all, which is what makes this safe.
    """
    cursor = 0
    for element in list(measure):
        if element.tag == "note":
            if element.find("chord") is None:
                cursor += _duration_of(element)
        elif element.tag == "forward":
            cursor += _duration_of(element)
        elif element.tag == "backup":
            back = _duration_of(element)
            if cursor <= 0:
                measure.remove(element)
                continue
            if back > cursor:
                element.find("duration").text = str(cursor)
                back = cursor
            cursor -= back


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


def _name_one(note: ET.Element, quarters: float) -> None:
    """Give one note a written value from its length, if one fits exactly."""
    name, dots, value = _nearest_value(quarters)
    if name is not None and abs(value - quarters) < 1e-6:
        _write_type(note, name, dots)


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


# The MusicXML marks that are drawn from a start to a stop.  Left open, each
# one runs to the end of the piece.
# `<tied>` is deliberately *not* here.  A tie carries no `number`, so adjacent
# ties all collide on one key and pairing them by key removes music that is
# perfectly well formed — it took out three real ties on the percussion part
# before this list was narrowed.  A tie also cannot run away: it joins one note
# to the next, and an unmatched one is drawn as a short hook, not across the
# piece.  Pairing ties properly means matching pitch and voice to the following
# note, which is a different job from this one.
_SPANNERS = {
    "slur": ("start", "stop"),
    "wedge": (("crescendo", "diminuendo"), "stop"),
    "octave-shift": (("up", "down"), "stop"),
    "pedal": ("start", "stop"),
    "bracket": ("start", "stop"),
    "dashes": ("start", "stop"),
}


def close_the_spanners(tree: ET.ElementTree) -> list[str]:
    """Throw away every drawn-from-here-to-there mark that cannot be what it says.

    Two things go, and they are different faults.

    **A mark with only one end.** A slur, a hairpin and a pedal are each written
    as two events, and recognition loses one of them often — a smudged hairpin
    tip, a tie whose second note was read as something else. What is left is not
    a small error: an unterminated spanner is drawn **to the end of the piece**.
    On the percussion part a crescendo opened at bar 50 and was still widening
    at bar 402, across nine systems and two pages, over music marked nothing of
    the kind.

    **A slur that changes voice.** A slur belongs to one voice; that is what a
    slur is. Where the scan has a *chord* of two unpitched notes tied over the
    barline — a snare and a bass drum struck together and rolled — Audiveris
    reads one of the two ties correctly and the other as a slur running from the
    upper voice to the lower one. LilyPond then draws an arc between two notes
    that are not in the same line of music, which comes out as a bow across half
    a system. Six of them on this part, at bars 71, 75, 76, 288 and 401.

    Nothing here can know where a lost end was meant to be, and guessing would
    put a crescendo where the composer did not, so the orphan is removed and
    reported. A stop with no start goes too: musicxml2ly answers a stray stop by
    ending the mark before it instead.
    """
    part = tree.getroot().find("part")
    if part is None:
        return []
    parent = {child: holder for holder in tree.getroot().iter() for child in holder}

    def voice_of(element: ET.Element) -> str | None:
        """The voice of the note this mark hangs on, if it hangs on one."""
        node = element
        while node is not None:
            if node.tag == "note":
                return node.findtext("voice")
            node = parent.get(node)
        return None

    open_at: dict[tuple[str, str], tuple[ET.Element, str, str | None]] = {}
    doomed: list[tuple[ET.Element, str, str]] = []
    for measure in part.findall("measure"):
        number = measure.get("number") or "?"
        for element in measure.iter():
            starts_with, stops_with = _SPANNERS.get(element.tag, (None, None))
            if starts_with is None:
                continue
            if element.tag == "slur" and element.get("number") is None:
                continue              # unnumbered slurs cannot be told apart
            kind = element.get("type")
            key = (element.tag, element.get("number", "1"))
            if kind == stops_with:
                if key not in open_at:
                    doomed.append((element, number, "a stop with no start"))
                    continue
                was, was_at, was_voice = open_at.pop(key)
                here = voice_of(element)
                if element.tag == "slur" and was_voice and here and was_voice != here:
                    why = (f"a slur from voice {was_voice} to voice {here}, which is "
                           f"not a slur — a chord's second tie read as one")
                    doomed.append((was, was_at, why))
                    doomed.append((element, number, why))
            elif kind == starts_with or (
                isinstance(starts_with, tuple) and kind in starts_with
            ):
                if key in open_at:                # a start over a start
                    was, was_at, _ = open_at[key]
                    doomed.append((was, was_at, "never stopped"))
                open_at[key] = (element, number, voice_of(element))
    for element, number, _voice in open_at.values():
        doomed.append((element, number, "never stopped"))

    notes: list[str] = []
    said: set[str] = set()
    for element, number, why in doomed:
        holder = parent.get(element)
        if holder is None:
            continue
        try:
            holder.remove(element)
        except ValueError:
            continue
        line = (f"measure {number}: a {element.tag} — {why}; removed rather than "
                f"drawn across music that has none")
        if line not in said:
            said.add(line)
            notes.append(line)
    _drop_empty_directions(part)
    return notes


def _drop_empty_directions(part: ET.Element) -> None:
    """A `<direction>` whose only content was the mark just removed."""
    for measure in part.findall("measure"):
        for direction in list(measure.findall("direction")):
            kinds = direction.findall("direction-type")
            if kinds and all(len(kind) == 0 for kind in kinds):
                measure.remove(direction)
