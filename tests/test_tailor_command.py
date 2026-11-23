import json
from datetime import date
from pathlib import Path

import pytest
from browser_marks import needs_browser
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.cover_letter import years_in_words
from resume_agent.documents import parse_resume
from resume_agent.guards.rules import lock_applied_files
from resume_agent.pipeline import (
    Mode,
    detect_mode,
    draft_letter,
    junior_companies,
    junior_drops,
    listing_ledger,
    tailor_folder,
)
from resume_agent.triage import YEARS_FILE

CURRENT = "Software Engineer @ Acme Health, 01/2023 - present"
EARLIER = "Junior Engineer @ Globex, 05/2021 - 08/2022"
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


def years_reply(years_max: int | None):
    return lambda _: json.dumps({"years_max": years_max})


def no_call(prompt: str) -> str:
    raise AssertionError("no requirements call expected")


def junior_run(prompt: str) -> str:
    if "hard requirements" in prompt:
        return years_reply(4)(prompt)
    return fake_run(prompt)


@pytest.fixture
def junior_config(config, config_data) -> Config:
    return Config(
        **{
            **config_data,
            "junior_listing": {
                "max_years": 4,
                "drop_companies": ["Globex"],
                "move_skills_to": "Acme Health",
                "max_moved_months": 3,
            },
        }
    )


@pytest.mark.parametrize(
    ("listing", "mode"),
    [
        ("Build FHIR integrations for an EHR.", Mode.UPWARD),
        ("Build payment services.", Mode.LATERAL),
    ],
)
def test_detect_mode(config, listing, mode):
    assert detect_mode(listing, config) is mode


@pytest.mark.parametrize(
    ("years_max", "dropped"),
    [
        (4, ["Globex"]),
        (5, []),
        (None, []),
    ],
)
def test_junior_listing_drops_companies(junior_config, folder, years_max, dropped):
    assert junior_companies(folder, "LISTING", junior_config, years_reply(years_max)) == dropped


def test_junior_listing_without_companies_skips_the_llm(config, folder):
    assert junior_companies(folder, "LISTING", config, no_call) == []


def test_junior_listing_reuses_the_years_saved_by_triage(junior_config, folder):
    (folder / YEARS_FILE).write_text(json.dumps({"years_max": 4}))

    assert junior_companies(folder, "LISTING", junior_config, no_call) == ["Globex"]


def test_junior_check_failure_keeps_every_role(junior_config, folder):
    resume = parse_resume(RESUME)

    companies, flags = junior_drops(resume, folder, "LISTING", junior_config, lambda _: "no")

    assert companies == []
    assert flags[0].startswith("Junior listing check skipped:")


def test_junior_company_missing_from_the_baseline_is_not_flagged(junior_config, folder):
    resume = parse_resume(RESUME)

    assert junior_drops(resume, folder, "LISTING", junior_config, years_reply(4)) == ([], [])


def test_letter_drops_the_same_junior_roles_as_tailor(junior_config, folder):
    source = junior_config.data_root / "baselines/general"
    (source / "resume.md").write_text(
        RESUME.replace("## Education", f"### {EARLIER}\n- Fixed pumps.\n## Education")
    )
    (source / "skills-ledger.yaml").write_text(
        LEDGER.replace("skills:", "  Globex:\n    from: 05/2021\n    to: 08/2022\nskills:")
    )
    prompts = []

    def run(prompt: str) -> str:
        prompts.append(prompt)
        return junior_run(prompt)

    _, flags = draft_letter(folder, junior_config, run)

    letter_prompt = prompts[-1]
    expected = years_in_words(listing_ledger(source, ["Globex"], junior_config).experience_months())
    assert f"use this exact number): {expected}" in letter_prompt
    assert "Fixed pumps." not in letter_prompt
    assert flags[0] == "Dropped for a listing capped at 4 years or fewer: Globex"


def test_letter_keeps_a_tailored_resume_with_the_trimmed_ledger(junior_config, folder):
    source = junior_config.data_root / "baselines/general"
    (source / "resume.md").write_text(
        RESUME.replace("## Education", f"### {EARLIER}\n- Fixed pumps.\n## Education")
    )
    (source / "skills-ledger.yaml").write_text(
        LEDGER.replace("skills:", "  Globex:\n    from: 05/2021\n    to: 08/2022\nskills:")
    )
    (folder / "resume.md").write_text(RESUME.replace("dozens of", "forty"))
    prompts = []

    def run(prompt: str) -> str:
        prompts.append(prompt)
        return junior_run(prompt)

    draft_letter(folder, junior_config, run)

    expected = years_in_words(listing_ledger(source, ["Globex"], junior_config).experience_months())
    assert "Built forty AWS Lambda functions." in prompts[-1]
    assert f"use this exact number): {expected}" in prompts[-1]


@needs_browser
def test_tailor_folder_drops_junior_roles(junior_config, folder):
    baseline = junior_config.data_root / "baselines/general/resume.md"
    baseline.write_text(
        RESUME.replace("## Education", f"### {EARLIER}\n- Fixed pumps.\n## Education")
    )

    tailor_folder(folder, junior_config, junior_run, today=date(2026, 11, 21))

    assert "Globex" not in (folder / "resume.md").read_text()
    assert (
        "Dropped for a listing capped at 4 years or fewer: Globex"
        in (folder / "diff.md").read_text()
    )


@needs_browser
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


@needs_browser
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
        "headline": "",
    }
    monkeypatch.setattr(cli, "run_prompt", lambda _, prompt: json.dumps(bad_plan))

    result = CliRunner().invoke(app, ["tailor", str(folder)])

    assert result.exit_code == 1
    assert "Headline is empty" in result.output
    assert not (folder / "resume.md").exists()


def test_tailor_command_without_listing(config, config_data, write_config, tmp_path):
    write_config(config_data)

    result = CliRunner().invoke(app, ["tailor", str(tmp_path)])

    assert result.exit_code == 1
    assert "listing.md" in result.output
