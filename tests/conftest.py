import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from make_fixture import draw_page, staff_tops, write_pdf  # noqa: E402

STAVES = 8
SPACE = 11
HEIGHT = 2480
TOP = 200


@pytest.fixture(scope="session")
def page_image():
    return draw_page(staves=STAVES, space=SPACE, height=HEIGHT, top=TOP)


@pytest.fixture(scope="session")
def expected_tops():
    return staff_tops(STAVES, SPACE, HEIGHT, TOP)


@pytest.fixture(scope="session")
def score_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("fixture") / "score.pdf"
    return write_pdf(path, pages=2, staves=STAVES, space=SPACE, height=HEIGHT, top=TOP)
