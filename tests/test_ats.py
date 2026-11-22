from pathlib import Path

import pytest

from resume_agent.ats import (
    GARBLED,
    REQUIRED_RESUME_HEADINGS,
    Check,
    check_pdf,
    cover_letter_expected_lines,
    report_markdown,
    resume_expected_lines,
    tokens,
)
from resume_agent.config import Config
from resume_agent.documents import parse_cover_letter, parse_resume
from resume_agent.render import cover_letter_html, render_pdf, resume_html

CHROME = Path("/Applications/Google Chrome.app")
needs_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome not installed")

RESUME = """---
headline: Software Engineer · TypeScript · AWS
---
## Experience
### Software Engineer
Acme Health, 01/2023 - present
- Built workflows for configurable office-based efficient fiscal pipelines.
- Wrote tests.
## Education
### BSc, Computer Science
State University
## Skills
- Languages: TypeScript, Python
"""


@pytest.fixture
def config(config_data) -> Config:
    return Config(
        **{
            **config_data,
            "name": "Jane Doe",
            "email": "jane.test+swe@example.com",
            "phone": "(555) 555-0100",
            "location": "Springfield, IL",
        }
    )


def test_tokens_drop_layout_markers():
    assert tokens("a@b.c | x\n- Built\n- Wrote - tests") == [
        "a@b.c",
        "x",
        "Built",
        "Wrote",
        "tests",
    ]


@pytest.mark.parametrize(
    ("text", "garbled"),
    [
        (f"work{chr(0xFB02)}ows", True),
        (f"bad {chr(0xFFFD)} glyph", True),
        (f"private {chr(0xE001)} glyph", True),
        ("(cid:12)", True),
        ("cross-functional 01/2023 - present", False),
    ],
)
def test_garbled_detection(text, garbled):
    assert bool(GARBLED.search(text)) is garbled


def test_report_markdown():
    report = report_markdown(
        "resume",
        [
            Check("A", True),
            Check("B", False, "why"),
        ],
    )

    assert "Overall: **FAIL**" in report
    assert "| B | FAIL | why |" in report


def test_info_checks_warn_without_failing_the_report():
    report = report_markdown(
        "resume",
        [
            Check("A", True),
            Check("Coverage", False, "90%", info=True),
        ],
    )

    assert "Overall: **PASS**" in report
    assert "| Coverage | WARN | 90% |" in report


@needs_chrome
def test_rendered_resume_passes_every_check(config, tmp_path):
    resume = parse_resume(RESUME)
    pdf = tmp_path / "resume.pdf"
    render_pdf(resume_html(resume, config), pdf)

    checks = check_pdf(pdf, resume_expected_lines(resume, config), config, REQUIRED_RESUME_HEADINGS)

    failed = [check for check in checks if not check.passed]
    assert failed == []


@needs_chrome
def test_rendered_cover_letter_passes_every_check(config, tmp_path):
    letter = parse_cover_letter("Dear Hiring Manager,\n\nI build things.\n\nBest,\n")
    pdf = tmp_path / "letter.pdf"
    render_pdf(cover_letter_html(letter, config), pdf)

    checks = check_pdf(pdf, cover_letter_expected_lines(letter, config), config)

    assert [check for check in checks if not check.passed] == []


@needs_chrome
def test_mismatch_and_missing_heading_fail(config, tmp_path):
    resume = parse_resume(RESUME)
    pdf = tmp_path / "resume.pdf"
    render_pdf(resume_html(resume, config), pdf)
    expected = [*resume_expected_lines(resume, config), "extra words"]

    checks = {check.rule: check for check in check_pdf(pdf, expected, config, ("Projects",))}

    assert not checks["Text round-trips exactly (pdfminer.six)"].passed
    assert not checks["Standard section headings"].passed
