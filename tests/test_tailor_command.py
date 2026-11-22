import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.guards.rules import lock_applied_files
from resume_agent.pipeline import Mode, detect_mode, tailor_folder

CHROME = Path("/Applications/Google Chrome.app")
needs_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome not installed")

CURRENT = "Software Engineer @ Acme Health, 01/2023 - present"
RESUME = f"""---
headline: Software Engineer | TypeScript
---
## Experience
### {CURRENT}
- Built dozens of AWS Lambda functions.
- Wrote Vitest tests.
## Education
BSc, Computer Science, State University
## Skills
- Languages: TypeScript
"""
LETTER_TEMPLATE = """---
title: Cover Letter
---

Dear [Hiring Manager's Name],

Over the past three years I have built things.

Best,
"""
LEDGER = """
roles:
  Acme Health:
    from: 01/2023
    to: present
skills:
  TypeScript:
    - role: Acme Health
  AWS Lambda:
    - role: Acme Health
  Vitest:
    - role: Acme Health
"""
PLAN = {
    "headline": "Backend Engineer | TypeScript | AWS Lambda",
    "roles": [
        {
            "heading": CURRENT,
            "bullets": [
                {
                    "source": "B1",
                    "text": "Built dozens of AWS Lambda functions in TypeScript.",
                },
            ],
        },
    ],
    "skills": ["Languages: TypeScript", "Cloud: AWS Lambda"],
}
LETTER = "Dear Hiring Team,\n\nOver the past three years I have built Lambdas for Globex.\n\nBest,"


@pytest.fixture
def config(config_data, data_root) -> Config:
    baseline = data_root / "baselines" / "general"
    baseline.mkdir(parents=True)
    (baseline / "resume.md").write_text(RESUME)
    (baseline / "cover-letter.md").write_text(LETTER_TEMPLATE)
    (baseline / "skills-ledger.yaml").write_text(LEDGER)
    return Config(**config_data)


@pytest.fixture
def folder(tmp_path) -> Path:
    path = tmp_path / "job"
    path.mkdir()
    (path / "listing.md").write_text(
        "Source: https://example.com/job\nTitle: Backend Engineer\n\nBuild TypeScript services.\n"
    )
    return path


def fake_run(prompt: str) -> str:
    return json.dumps(PLAN) if "Tailor a resume" in prompt else LETTER


@pytest.mark.parametrize(
    ("listing", "mode"),
    [
        ("Build FHIR integrations for an EHR.", Mode.UPWARD),
        ("Build payment services.", Mode.LATERAL),
    ],
)
def test_detect_mode(config, listing, mode):
    assert detect_mode(listing, config) is mode


@needs_chrome
def test_tailor_folder_writes_every_file(config, folder):
    result = tailor_folder(folder, config, fake_run, today=date(2026, 11, 21))

    assert result.mode is Mode.LATERAL
    assert result.render.passed
    resume = (folder / "resume.md").read_text()
    assert "Built dozens of AWS Lambda functions in TypeScript." in resume
    assert "Dear Hiring Team," in (folder / "cover-letter.md").read_text()
    assert "- [B1] reworded:" in (folder / "diff.md").read_text()
    notes = (folder / "notes.md").read_text()
    assert "- Baseline: general" in notes
    assert "- Mode: lateral" in notes
    assert (folder / "First-Last-Resume.pdf").exists()


@needs_chrome
def test_locked_folder_is_tailored_into_drafts(config, folder):
    for name in ("resume.md", "cover-letter.md"):
        (folder / name).write_text("applied version")
    lock_applied_files(folder, ["resume.md", "cover-letter.md"], today=date(2026, 11, 20))
    lock_notes = (folder / "notes.md").read_text()

    result = tailor_folder(folder, config, fake_run, today=date(2026, 11, 21))

    assert result.folder == folder / "drafts"
    assert (folder / "resume.md").read_text() == "applied version"
    assert (folder / "notes.md").read_text() == lock_notes
    assert "Built dozens of AWS Lambda functions" in (folder / "drafts/resume.md").read_text()
    assert (folder / "drafts/notes.md").exists()


def test_tailor_command_reports_rule_breaks(config, config_data, write_config, folder, monkeypatch):
    write_config(config_data)
    bad_plan = {
        **PLAN,
        "skills": ["Cloud: Kubernetes"],
    }
    monkeypatch.setattr(cli, "run_prompt", lambda _, prompt: json.dumps(bad_plan))

    result = CliRunner().invoke(app, ["tailor", str(folder)])

    assert result.exit_code == 1
    assert "Skill 'Kubernetes' is not in the skills ledger" in result.output
    assert not (folder / "resume.md").exists()


def test_tailor_command_without_listing(config, config_data, write_config, tmp_path):
    write_config(config_data)

    result = CliRunner().invoke(app, ["tailor", str(tmp_path)])

    assert result.exit_code == 1
    assert "listing.md" in result.output
