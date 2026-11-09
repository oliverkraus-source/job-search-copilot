import textwrap
from pathlib import Path

import pytest

from jobcopilot.config import load_config

CV = textwrap.dedent("""\
    # Sam Example (fictional)
    ## Experience
    - Shift supervisor, led a team of 12 warehouse employees per shift
    - Built a React app for booking climbing gym slots
    ## Skills
    - JavaScript, React, Git
    - German (native), English (C1)
    """)

CONFIG = textwrap.dedent("""\
    [me]
    name = "Sam Example"
    cv = "cv.md"
    portfolio_url = "https://sam.example"
    [search]
    role_keywords = ["IT-Support", "Helpdesk", "Developer", "Fachinformatiker"]
    level_keywords = ["Junior", "Ausbildung", "Quereinsteiger"]
    text_keywords = ["Quereinsteiger", "English", "Deutsch"]
    exclude_title = ["Senior", "Sr", "Werkstudent", "Business Developer"]
    exclude_text = ["5+ years"]
    remote_regions = ["Worldwide", "Europe"]
    """)


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    (tmp_path / "cv.md").write_text(CV, encoding="utf-8")
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def cfg(cfg_path):
    return load_config(cfg_path)
