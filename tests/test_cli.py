from sheeets.cli import main


def test_inspect_reports_each_page(score_pdf, capsys):
    assert main(["inspect", str(score_pdf)]) == 0
    out = capsys.readouterr().out
    assert "systems=1" in out
    assert "staves=[8]" in out
    assert "total staves: 16" in out


def test_inspect_writes_a_numbered_overlay(score_pdf, tmp_path, capsys):
    main(["inspect", str(score_pdf), "--pages", "1", "--overlay", str(tmp_path / "ov")])
    files = list((tmp_path / "ov").glob("*.png"))
    assert len(files) == 1


def test_extract_writes_a_pdf(score_pdf, tmp_path, capsys):
    out = tmp_path / "part.pdf"
    assert main(["extract", str(score_pdf), "--part", "bottom", "-o", str(out),
                 "--name", "Perc", "--quiet"]) == 0
    assert out.exists() and out.stat().st_size > 1000
    assert "Perc" in capsys.readouterr().out


def test_extract_reports_failure_when_nothing_matched(score_pdf, tmp_path, capsys):
    out = tmp_path / "part.pdf"
    assert main(["extract", str(score_pdf), "--part", "40", "-o", str(out), "--quiet"]) == 1
