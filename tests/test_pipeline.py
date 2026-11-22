from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.pipeline import pdf_name

CHROME = Path("/Applications/Google Chrome.app")
needs_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome not installed")

RESUME = """---
headline: Software Engineer · AWS
---
## Experience
### Software Engineer
Acme Health, 01/2023 - present
- Built Lambdas.
## Education
### BSc, Computer Science
State University
## Skills
- Languages: TypeScript
"""
LETTER = "Dear Hiring Manager,\n\nI build things.\n\nBest,\n"


@pytest.mark.parametrize(
    ("person", "expected"),
    [
        ("Jane Doe", "Jane-Doe-Resume.pdf"),
        ("  Ana  María López ", "Ana-María-López-Resume.pdf"),
    ],
)
def test_pdf_name(person, expected):
    assert pdf_name(person, "Resume") == expected


@needs_chrome
def test_render_command_on_baseline(config_data, write_config, data_root):
    config_data = {
        **config_data,
        "name": "Jane Doe",
        "email": "jane@example.com",
        "location": "Springfield, IL",
    }
    write_config(config_data)
    baseline = data_root / "baselines" / "general"
    baseline.mkdir(parents=True)
    (baseline / "resume.md").write_text(RESUME)
    (baseline / "cover-letter.md").write_text(LETTER)

    result = CliRunner().invoke(app, ["render"])

    assert result.exit_code == 0, result.output
    assert (baseline / "Jane-Doe-Resume.pdf").exists()
    assert (baseline / "Jane-Doe-Cover-Letter.pdf").exists()
    assert "Overall: **PASS**" in (baseline / "ats-report.md").read_text()


@needs_chrome
def test_render_command_named_baseline_failing_ats(config_data, write_config, data_root):
    write_config(config_data)
    baseline = data_root / "baselines" / "full-stack"
    baseline.mkdir(parents=True)
    long_bullets = "".join(f"- Built feature number {n} end-to-end.\n" for n in range(80))
    (baseline / "resume.md").write_text(RESUME + long_bullets)
    (baseline / "cover-letter.md").write_text(LETTER)

    result = CliRunner().invoke(app, ["render", "--baseline", "full-stack"])

    assert result.exit_code == 1
    assert "ATS FAIL" in result.output
    assert "| Exactly 1 page | FAIL |" in (baseline / "ats-report.md").read_text()


def test_render_command_missing_sources_clears_old_report(config_data, write_config, tmp_path):
    write_config(config_data)
    (tmp_path / "ats-report.md").write_text("Overall: **PASS**")

    result = CliRunner().invoke(app, ["render", str(tmp_path)])

    assert result.exit_code == 1
    assert "resume.md" in result.output
    assert not (tmp_path / "ats-report.md").exists()


def test_render_command_rejects_folder_and_baseline(config_data, write_config, tmp_path):
    write_config(config_data)

    result = CliRunner().invoke(app, ["render", str(tmp_path), "--baseline", "general"])

    assert result.exit_code == 1
    assert "not both" in result.output
