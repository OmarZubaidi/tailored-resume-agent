from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.cli import app
from resume_agent.job_listing import Listing, save_listing

BASELINE_RESUME = """---
headline: Software Engineer | TypeScript
---
## Experience
### Software Engineer @ Acme Health, 01/2023 - present
- Built dozens of AWS Lambda functions.
## Education
BSc, Computer Science, State University
## Skills
- Languages: TypeScript
"""
TEMPLATE = """---
title: Cover Letter
---

Dear [Hiring Manager's Name],

Over the past three years I have built things for people who needed them built.

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
"""
LETTER = "Dear Hiring Team,\n\nI have built Lambdas for three years and would like to build at"
LETTER += " Globex.\n\nBest,"


@pytest.fixture
def prompts(config_data, write_config, data_root, monkeypatch) -> list[str]:
    baseline = data_root / "baselines/general"
    baseline.mkdir(parents=True)
    (baseline / "resume.md").write_text(BASELINE_RESUME)
    (baseline / "cover-letter.md").write_text(TEMPLATE)
    (baseline / "skills-ledger.yaml").write_text(LEDGER)
    (data_root / "style").mkdir()
    (data_root / "style/voice.md").write_text("Direct and practical.")
    write_config(config_data)
    sent = []

    def fake_run(_, prompt):
        sent.append(prompt)
        return LETTER

    monkeypatch.setattr(cli, "run_prompt", fake_run)
    return sent


@pytest.fixture
def listing_folder(data_root) -> Path:
    folder = data_root / "style/test-listings/globex"
    folder.mkdir(parents=True)
    save_listing(
        Listing(
            source="https://jobs.example.com/globex/1",
            title="Backend Engineer",
            text="Globex builds logistics software. Requires TypeScript.",
        ),
        folder,
    )
    return folder


def test_letter_drafts_into_numbered_files(prompts, listing_folder):
    first = CliRunner().invoke(app, ["letter", str(listing_folder)])
    second = CliRunner().invoke(app, ["letter", str(listing_folder)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    drafts = sorted(path.name for path in (listing_folder / "drafts").iterdir())
    assert drafts == ["cover-letter-01.md", "cover-letter-02.md"]
    assert "Lambdas for three years" in (listing_folder / "drafts/cover-letter-02.md").read_text()
    assert not (listing_folder / "cover-letter.md").exists()


def test_letter_numbers_after_the_highest_draft(prompts, listing_folder):
    drafts = listing_folder / "drafts"
    drafts.mkdir()
    (drafts / "cover-letter-03.md").write_text("kept")

    CliRunner().invoke(app, ["letter", str(listing_folder)])

    assert (drafts / "cover-letter-03.md").read_text() == "kept"
    assert (drafts / "cover-letter-04.md").exists()


def test_letter_uses_voice_and_baseline_resume_without_a_tailored_one(prompts, listing_folder):
    CliRunner().invoke(app, ["letter", str(listing_folder)])

    assert "Direct and practical." in prompts[0]
    assert "Built dozens of AWS Lambda functions." in prompts[0]


def test_letter_includes_story_notes(prompts, listing_folder, data_root):
    notes = "## Fax product\n\n- Why it exists: cheapest HIPAA-compliant channel."
    (data_root / "baselines/general/story-notes.md").write_text(notes)

    CliRunner().invoke(app, ["letter", str(listing_folder)])

    assert "cheapest HIPAA-compliant channel" in prompts[0]


def test_letter_without_story_notes_says_so(prompts, listing_folder):
    CliRunner().invoke(app, ["letter", str(listing_folder)])

    assert "Tell stories from the resume's facts alone." in prompts[0]


def test_letter_prefers_the_folder_resume(prompts, listing_folder):
    tailored = BASELINE_RESUME.replace("dozens of", "forty")
    (listing_folder / "resume.md").write_text(tailored)

    CliRunner().invoke(app, ["letter", str(listing_folder)])

    assert "Built forty AWS Lambda functions." in prompts[0]


def test_letter_without_listing_fails(prompts, data_root):
    result = CliRunner().invoke(app, ["letter", str(data_root)])

    assert result.exit_code == 1
