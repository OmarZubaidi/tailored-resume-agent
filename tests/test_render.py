import re
from html import escape
from pathlib import Path

import pytest

from resume_agent.config import Config
from resume_agent.documents import parse_cover_letter, parse_resume
from resume_agent.render import (
    CSS,
    REGULAR_SPACE,
    RenderError,
    cover_letter_html,
    render_pdf,
    resume_html,
    role_heading_html,
    text_html,
)

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


def test_text_html_uses_regular_weight_spaces():
    assert text_html("a <b> c") == f"a{REGULAR_SPACE}&lt;b&gt;{REGULAR_SPACE}c"


def test_resume_html_escapes_and_contains_contact(config):
    html = resume_html(parse_resume(RESUME), config).replace(REGULAR_SPACE, " ")

    assert "Built &lt;fast&gt; Lambdas &amp; tests." in html
    email_link = f'<a href="mailto:{config.email}">{config.email}</a>'
    assert f'<span class="item">{email_link}</span> | ' in html
    assert config.phone in html
    assert config.location in html
    assert '<span class="skill-label">Languages:</span> TypeScript, Python' in html
    assert "Software Engineer · TypeScript" in html


def test_role_heading_splits_title_from_company():
    html = role_heading_html("Software Engineer @ Acme Health, 01/2023 - present").replace(
        REGULAR_SPACE, " "
    )

    assert html == (
        '<span class="role-title">Software Engineer</span> @ '
        '<span class="role-subtitle">Acme Health, 01/2023 - present</span>'
    )


def test_role_heading_without_company():
    html = role_heading_html("BSc, Computer Science").replace(REGULAR_SPACE, " ")

    assert html == '<span class="role-title">BSc, Computer Science</span>'


def test_roles_without_bullets_are_compact(config):
    resume = parse_resume("## Experience\n### Field Technician @ Globex, 01/2016 - 11/2019\n")

    assert '<div class="role compact">' in resume_html(resume, config)


def test_cover_letter_html_has_signature_block(config):
    letter = parse_cover_letter("Dear Hiring Manager,\n\nI build things.\n\nBest,\n")

    html = cover_letter_html(letter, config).replace(REGULAR_SPACE, " ")

    assert "<h2>Cover Letter</h2>" in html
    assert "<p>I build things.</p>" in html
    signature = html.split("<p>Best,")[1]
    assert signature.startswith(f"<br>{config.name}<br>")
    assert f"<br>{escape(config.location)}</p>" in signature
    assert "github" not in signature
    assert "linkedin" not in signature


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
