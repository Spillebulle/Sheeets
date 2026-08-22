import json

import pytest

from sheeets import extract_part
from sheeets.paper import PageSetup
from sheeets.sources import PdfSource, parse_pages
from tests.conftest import SPACE, STAVES


def test_parse_pages():
    assert parse_pages("3-", 6) == [2, 3, 4, 5]
    assert parse_pages("1,3,5-6", 6) == [0, 2, 4, 5]
    assert parse_pages(None, 3) == [0, 1, 2]
    assert parse_pages("9", 3) == []


def test_native_dpi_is_read_off_the_scan(score_pdf):
    assert PdfSource(score_pdf).native_dpi() == pytest.approx(300, abs=2)


def test_extracts_the_bottom_staff_from_every_page(score_pdf, tmp_path, expected_tops):
    out = tmp_path / "part.pdf"
    result = extract_part(score_pdf, part="bottom", out=out)
    assert out.exists()
    assert result.pages_used == [0, 1]
    assert result.segments
    assert not result.warnings
    # Every piece comes from the band around the last staff, not another one.
    bottom = expected_tops[-1]
    for segment in result.segments:
        assert segment.band.y0 < bottom < segment.band.y1
        assert segment.band.staff_index == STAVES - 1


def test_a_wide_system_is_cut_into_pieces_and_a_narrow_page_is_not(score_pdf, tmp_path):
    wide = extract_part(score_pdf, part="bottom", setup=PageSetup(staff_mm=1.75))
    small = extract_part(score_pdf, part="bottom", setup=PageSetup(staff_mm=0.4))
    assert max(s.of for s in wide.segments) > 1
    assert max(s.of for s in small.segments) == 1


def test_selecting_all_staves_keeps_them_together(score_pdf):
    result = extract_part(score_pdf, part="all")
    assert result.segments
    band = result.segments[0].band
    assert band.height > 6 * SPACE * STAVES / 2  # one band spanning the page


def test_manifest_round_trips(score_pdf, tmp_path):
    out = tmp_path / "geometry.json"
    extract_part(score_pdf, part="bottom", out=out)
    data = json.loads(out.read_text())
    assert data["sheeets"] == 1
    assert data["pages_used"] == [1, 2]
    assert len(data["pages"]) == 2
    assert data["pages"][0]["systems"][0]["staves"][-1]["index"] == STAVES - 1
    assert data["segments"]


def test_images_export_names_pieces_in_playing_order(score_pdf, tmp_path):
    folder = tmp_path / "pngs"
    result = extract_part(score_pdf, part="bottom", out=folder)
    files = sorted(p.name for p in folder.glob("*.png"))
    assert len(files) == len(result.segments)
    assert files == sorted(files)  # sorting by name is playing order


def test_a_missing_part_is_a_warning_not_a_crash(score_pdf):
    result = extract_part(score_pdf, part="40")
    assert result.segments == []
    assert any("no staff matched" in w for w in result.warnings)
