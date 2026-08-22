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

        total = Fraction(0)
        counted = 0
        whole_bar_rest = False
        for note in measure.findall("note"):
            if note.find("chord") is not None:
                continue  # a chord sounds with the note before it
            counted += 1
            rest = note.find("rest")
            if rest is not None and rest.get("measure") == "yes":
                # A bar's rest, or a multi-bar rest — one written measure
                # whatever its duration says, which is how it is counted in the
                # scan too.
                whole_bar_rest = True
                continue
            duration = note.findtext("duration")
            if duration is not None:
                total += Fraction(int(duration), divisions * 4)
            else:
                kind = note.findtext("type")
                total += Fraction(TYPE_LENGTH.get(kind, 0))
        if whole_bar_rest and total == 0:
            total = expected
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
