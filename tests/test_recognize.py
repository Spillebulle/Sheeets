"""The recognition seam: no engine ships, but the wiring is real and tested."""

import pytest

from sheeets import extract_part
from sheeets.export.musicxml import MusicXmlExporter
from sheeets.recognize import ExternalRecognizer, get_recognizer, registered

# A stand-in for an OMR program: reads one page image, writes one measure.
FAKE_OMR = '''
import pathlib, sys
inp, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
for n, image in enumerate(sorted(inp.glob("*.png")), start=1):
    (out / (image.stem + ".musicxml")).write_text("""<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
""")
'''


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    script = tmp_path / "omr.py"
    script.write_text(FAKE_OMR)
    command = f"python3 {script} {{input}} {{output}}"
    monkeypatch.setenv("SHEEETS_OMR_COMMAND", command)
    return ExternalRecognizer()


def test_the_engines_are_registered_whether_or_not_they_are_installed():
    assert {"oemer", "audiveris", "external"} <= set(registered())


def test_no_engine_means_a_sentence_not_an_empty_file(score_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr("sheeets.recognize._REGISTRY", {})
    result = extract_part(score_pdf, part="bottom")
    with pytest.raises(RuntimeError, match="SHEEETS_OMR_COMMAND"):
        MusicXmlExporter().write(result, tmp_path / "part.musicxml")
    assert not (tmp_path / "part.musicxml").exists()


def test_an_engine_is_handed_one_page_at_a_time_and_the_pages_are_joined(
    score_pdf, tmp_path, fake_engine, monkeypatch
):
    monkeypatch.setattr("sheeets.recognize._REGISTRY", {"external": fake_engine})
    assert fake_engine.available()
    result = extract_part(score_pdf, part="bottom")
    out = tmp_path / "part.musicxml"
    MusicXmlExporter().write(result, out)
    text = out.read_text()
    # One measure per piece, renumbered into a single run.
    assert text.count("<measure ") == len(result.segments)
    assert f'number="{len(result.segments)}"' in text


def test_get_recognizer_ignores_one_that_is_not_installed(monkeypatch):
    monkeypatch.setattr("sheeets.recognize._REGISTRY", {"external": ExternalRecognizer()})
    monkeypatch.setenv("SHEEETS_OMR_COMMAND", "definitely-not-installed {input} {output}")
    assert get_recognizer() is None
    monkeypatch.delenv("SHEEETS_OMR_COMMAND")
    assert get_recognizer("external") is None
