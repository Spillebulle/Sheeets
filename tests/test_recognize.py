"""The MusicXML seam: not implemented, but wired up and honest about it."""

import pytest

from sheeets import extract_part
from sheeets.export.musicxml import MusicXmlExporter
from sheeets.recognize import ExternalRecognizer, get_recognizer

FAKE_OMR = '''
import pathlib, sys
inp, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
pages = len(list(inp.glob("*.png")))
(out / "part.musicxml").write_text("<score-partwise pages=" + str(pages) + "/>")
'''


@pytest.fixture
def fake_omr(tmp_path, monkeypatch):
    script = tmp_path / "omr.py"
    script.write_text(FAKE_OMR)
    command = f"python3 {script} {{input}} {{output}}"
    monkeypatch.setenv("SHEEETS_OMR_COMMAND", command)
    return command


def test_no_engine_means_a_sentence_not_an_empty_file(score_pdf, tmp_path, monkeypatch):
    monkeypatch.delenv("SHEEETS_OMR_COMMAND", raising=False)
    result = extract_part(score_pdf, part="bottom")
    with pytest.raises(RuntimeError, match="SHEEETS_OMR_COMMAND"):
        MusicXmlExporter().write(result, tmp_path / "part.musicxml")
    assert not (tmp_path / "part.musicxml").exists()


def test_an_external_engine_is_handed_the_pieces(score_pdf, tmp_path, fake_omr):
    recognizer = ExternalRecognizer()
    assert recognizer.available()
    result = extract_part(score_pdf, part="bottom")
    out = tmp_path / "part.musicxml"
    MusicXmlExporter().write(result, out, recognizer=None)
    text = out.read_text()
    assert text.startswith("<score-partwise")
    # It saw one image per piece, in playing order.
    assert f"pages={len(result.segments)}" in text


def test_get_recognizer_ignores_one_that_is_not_installed(monkeypatch):
    monkeypatch.setenv("SHEEETS_OMR_COMMAND", "definitely-not-installed {input} {output}")
    assert get_recognizer() is None
