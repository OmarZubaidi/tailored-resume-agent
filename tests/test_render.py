import re
from pathlib import Path

import pytest

from resume_agent.config import Config
from resume_agent.documents import parse_resume
from resume_agent.render import CSS, RenderError, render_pdf, resume_html

CHROME = Path("/Applications/Google Chrome.app")
needs_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome not installed")

RESUME = """---
headline: Software Engineer · TypeScript
---
## Experience
### Software Engineer
Acme Health, 01/2023 - present
- Built <fast> Lambdas & tests.
## Skills
- Languages: TypeScript, Python
"""


@pytest.fixture
def config(config_data) -> Config:
    return Config(**config_data)


def test_ligatures_disabled():
    assert "font-variant-ligatures: none" in CSS
    assert '"liga" 0, "clig" 0, "dlig" 0' in CSS


def test_resume_html_escapes_and_contains_contact(config):
    html = resume_html(parse_resume(RESUME), config)

    assert "Built &lt;fast&gt; Lambdas &amp; tests." in html
    assert f'<a href="mailto:{config.email}">{config.email}</a>' in html
    assert config.phone in html
    assert config.location in html
    assert '<span class="skill-label">Languages:</span> TypeScript, Python' in html
    assert "Software Engineer · TypeScript" in html


@needs_chrome
def test_render_pdf_writes_one_letter_page(config, tmp_path):
    output = tmp_path / "resume.pdf"

    render_pdf(resume_html(parse_resume(RESUME), config), output)

    data = output.read_bytes()
    assert data.startswith(b"%PDF")
    assert re.search(rb"/Count 1\b", data)
    assert re.search(rb"/MediaBox \[0 0 612 792\]", data)


@needs_chrome
def test_contact_line_over_two_rows_fails(config, tmp_path):
    long_config = config.model_copy(update={"location": "x" * 200})

    with pytest.raises(RenderError, match="Contact line needs"):
        render_pdf(resume_html(parse_resume(RESUME), long_config), tmp_path / "r.pdf")
