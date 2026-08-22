"""Splitting a book of parts.

A band library's PDF is often the whole set in one file: the solo cornet's
pages, then the repiano's, then the horns', thirty-two pages of it.  Before any
of that can be treated as a part, the file has to be cut into parts.

The signal is not the page margin — measured across such a book the first
staff sits anywhere from 9 % to 26 % down the page whether or not the part
changes.  It is the **title**.  Every part's first page carries the title of
the piece at the top, next to that player's name; continuation pages carry at
most a short corner header.  So:

1.  Read the strip above the first staff on every page.
2.  Work out the title: the line that recurs, normalised to letters only, so
    that "RULE BRITANNIA." and "RULE B RITANNIA”" are the same string.
3.  A page whose header holds the title begins a part; the rest of that header
    names the player.

Measured on a 32-page book this finds the boundaries exactly, including the
pages where OCR of the music itself is nonsense — the header only has to be
legible enough to spot one long word in it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

INSTRUMENTS = (
    "cornet", "trumpet", "horn", "flugel", "flugelhorn", "baritone", "trombone",
    "euphonium", "bass", "tuba", "timpani", "percussion", "drum", "drums",
    "soprano", "repiano", "clarinet", "flute", "piccolo", "oboe", "bassoon",
    "saxophone", "sax", "violin", "viola", "cello", "contrabass", "piano",
    "harp", "glockenspiel", "xylophone", "vibraphone", "marimba", "snare",
    "cymbal", "tambourine", "conductor", "score", "solo", "soloist", "tenor",
    "alto", "kit", "trommesett", "slagverk",
)

QUALIFIERS = ("solo", "soloist", "repiano", "1st", "2nd", "3rd", "4th", "first",
              "second", "third", "fourth", "principal", "sub", "optional")


@dataclass
class PartRange:
    """One player's pages inside a book."""

    name: str
    first_page: int  # 1-based, as a PDF reader shows it
    last_page: int
    header: str = ""

    @property
    def pages(self) -> str:
        return f"{self.first_page}-{self.last_page}"

    @property
    def count(self) -> int:
        return self.last_page - self.first_page + 1


@dataclass
class Book:
    parts: list[PartRange] = field(default_factory=list)
    title: str = ""
    headers: dict[int, str] = field(default_factory=dict)

    def as_cases(self, source: str) -> list[dict]:
        """The parts, in the shape `tools/fleet.py` reads."""
        return [
            {"name": _slug(p.name), "source": source, "part": "all",
             "pages": p.pages, "label": p.name}
            for p in self.parts
        ]


def letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def read_header(image: np.ndarray, first_staff_top: float, margin: int = 5) -> str:
    """OCR the strip above the topmost staff."""
    if not shutil.which("tesseract"):
        return ""
    band = image[: max(0, int(first_staff_top) - margin), :]
    if band.size == 0 or band.shape[0] < 10:
        return ""
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="sheeets-header-") as tmp:
        path = Path(tmp) / "header.png"
        Image.fromarray(band).save(path)
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "6"],
            capture_output=True, text=True,
        )
    return result.stdout if result.returncode == 0 else ""


def find_title(headers: dict[int, str], min_length: int = 8) -> str:
    """The piece's title: the longest run of letters that turns up on several pages.

    It has to be looked for *inside* the headers rather than as a whole line.
    On a part's first page the title usually shares its line with the player
    and the composer — "Soprano  RULE BRITANNIA  J. HARTMANN" — so the lines
    themselves never repeat, but the title inside them does.  Comparing
    letters only also makes the OCR's mangling harmless: "RULE BRITANNIA." and
    "RULE B RITANNIA”" are the same thirteen letters.
    """
    normalised = {index: letters(text) for index, text in headers.items()}
    candidates: set[str] = set()
    for text in headers.values():
        for line in text.splitlines():
            key = letters(line)
            if len(key) >= min_length:
                candidates.add(key)
                # A line that carries the title plus other words: try the
                # longest runs of it too, so the title can be found inside.
                for size in range(len(key) - 1, min_length - 1, -1):
                    for start in range(0, len(key) - size + 1):
                        candidates.add(key[start : start + size])
                    if len(candidates) > 20000:
                        break
    best = ""
    best_count = 0
    for candidate in candidates:
        count = sum(1 for text in normalised.values() if candidate in text)
        if count < 2:
            continue
        if count > best_count or (count == best_count and len(candidate) > len(best)):
            best, best_count = candidate, count
    return best


def starts_a_part(header: str, title_key: str) -> bool:
    """Does this page begin a new player's music?

    The title alone is nearly enough — every first page carries it and no
    continuation page does — but OCR truncates it now and then ("RULE BRI"),
    and one part of a twenty-part book was swallowed by the one before it.  So
    two weaker signals are added and two of the three must agree:

    * the title, in full;
    * enough of the title to be unmistakable (six letters of it);
    * a line that *begins* with a player's name, which is how a first page is
      laid out and a corner header is not — "Solo Horn ..." starts a part,
      "ss dali, Cornet tn B?" is page two of one.
    """
    text = letters(header)
    if not text:
        return False
    score = 0
    if title_key and title_key in text:
        score += 2
    elif title_key and len(title_key) >= 6:
        for size in range(len(title_key), 5, -1):
            if title_key[:size] in text:
                score += 1
                break
    for line in header.splitlines():
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9.'’]*", line.strip())
        for word in words[:2]:
            key = letters(word)
            if key in INSTRUMENTS or key in QUALIFIERS or re.fullmatch(r"\d(st|nd|rd|th)", word.lower()):
                score += 1
                break
        else:
            continue
        break
    return score >= 2


def name_from(header: str, title_key: str) -> str:
    """The player's name on a part's first page, with the title taken out."""
    best = ""
    for line in header.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9.'’♭]*", stripped)
        keep: list[str] = []
        for word in words:
            key = letters(word)
            if title_key and key and key in title_key and len(key) > 3:
                continue  # part of the title
            if not key and not any(c.isdigit() for c in word):
                continue
            keep.append(_tidy(word))
            if key in INSTRUMENTS and len(keep) <= 4:
                candidate = " ".join(keep).strip(" .'")
                if len(candidate) > len(best):
                    best = candidate
            elif best and _tidy(word) in PITCHES and len(keep) <= 5:
                # "Bass Eb" and "Bass Bb" are different players; the pitch
                # belongs to the name even though it follows the instrument.
                best = f"{best} {_tidy(word)}"
        if best:
            break
    return best


PITCHES = ("Eb", "Bb", "F", "C", "A")

# What OCR reliably mangles in a part name, and what it should have said.
MISREADS = {
    "ist": "1st", "lst": "1st", "dad": "2nd", "and": "2nd", "ond": "2nd",
    "gnd": "2nd", "3ra": "3rd", "fuge": "Flugel", "fugel": "Flugel",
    "fuge!": "Flugel", "bh": "Bb", "eb": "Eb", "bb": "Bb",
}


def _tidy(word: str) -> str:
    """Undo the handful of misreadings that turn up in part names."""
    key = word.lower().strip(".'’")
    return MISREADS.get(key, word.strip(".'’"))


def split(detected, source_name: str = "") -> Book:
    """Work out which pages belong to which player.

    `detected` is a list of `DetectedPage`, which is what `sheeets.analyse`
    returns — the headers are read off the deskewed images it already made.
    """
    headers: dict[int, str] = {}
    tops: dict[int, float] = {}
    for page in detected:
        if not page.staves:
            continue
        top = min(s.top for s in page.staves)
        tops[page.page.index] = top
        headers[page.page.index] = read_header(page.image, top)

    title_key = find_title(headers)
    starts: list[int] = []
    for index in sorted(headers):
        if starts_a_part(headers[index], title_key):
            starts.append(index)
    if not starts and headers:
        starts = [min(headers)]

    parts: list[PartRange] = []
    ordered = sorted(headers)
    for n, start in enumerate(starts):
        end = starts[n + 1] - 1 if n + 1 < len(starts) else ordered[-1]
        name = name_from(headers[start], title_key) or f"part {n + 1}"
        parts.append(PartRange(name=name, first_page=start + 1, last_page=end + 1,
                               header=headers[start].strip().splitlines()[0][:60]
                               if headers[start].strip() else ""))
    return Book(parts=parts, title=title_key, headers=headers)


def _slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", (text or "").lower())).strip("-") or "part"


def write_parts(source, found: Book, folder: Path) -> list[Path]:
    """One PDF per player, carved out of the book."""
    import pymupdf

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with pymupdf.open(source) as document:
        for n, part in enumerate(found.parts, start=1):
            out = folder / f"{n:02d}-{_slug(part.name)}.pdf"
            piece = pymupdf.open()
            piece.insert_pdf(document, from_page=part.first_page - 1,
                             to_page=part.last_page - 1)
            piece.save(out)
            piece.close()
            written.append(out)
    return written
