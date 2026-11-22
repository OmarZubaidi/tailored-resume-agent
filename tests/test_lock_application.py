from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent import pipeline
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.guards.rules import GuardError, excel_lock_file, is_locked
from resume_agent.pipeline import applied_files, lock_application
from resume_agent.tracker import (
    Application,
    Stage,
    Tracker,
    load_tracker,
    save_tracker,
    workbook_path,
)

DAY = date(2026, 11, 21)
FOLDER = "00001 Acme Health - Software Engineer (2026-11-20)"


@pytest.fixture
def config(config_data, write_config, data_root) -> Config:
    data_root.mkdir(parents=True)
    write_config(config_data)
    return Config(**config_data)


@pytest.fixture
def folder(config) -> Path:
    path = config.data_root / "applications" / FOLDER
    path.mkdir(parents=True)
    for name in applied_files(config):
        (path / name).write_text(f"generated {name}")
    return path


@pytest.fixture
def ats_runs(monkeypatch) -> list[Path]:
    runs = []

    def fake_report(folder: Path, config: Config) -> bool:
        runs.append(folder)
        return True

    monkeypatch.setattr(pipeline, "write_ats_report", fake_report)
    return runs


def test_lock_application_locks_sources_and_pdfs(config, folder, ats_runs):
    assert lock_application(folder, config, DAY)

    assert all(is_locked(folder / name) for name in applied_files(config))
    assert ats_runs == [folder]
    assert (folder / "notes.md").read_text().count("locked") == 4


def test_handed_over_pdf_replaces_generated_one(config, folder, ats_runs, tmp_path):
    handed = tmp_path / "edited.pdf"
    handed.write_text("hand edited")

    lock_application(folder, config, DAY, resume_file=handed)

    resume_pdf = folder / "First-Last-Resume.pdf"
    assert resume_pdf.read_text() == "hand edited"
    assert is_locked(resume_pdf)
    assert "`First-Last-Resume.pdf` replaced with `edited.pdf`" in (folder / "notes.md").read_text()


def test_handover_after_lock_is_refused(config, folder, ats_runs, tmp_path):
    lock_application(folder, config, DAY)
    handed = tmp_path / "edited.pdf"
    handed.write_text("hand edited")

    with pytest.raises(GuardError, match="Already locked"):
        lock_application(folder, config, DAY, letter_file=handed)


def test_partly_locked_handover_changes_nothing(config, folder, ats_runs, tmp_path):
    letter_pdf = folder / "First-Last-Cover-Letter.pdf"
    letter_pdf.chmod(0o444)
    resume, letter = tmp_path / "resume.pdf", tmp_path / "letter.pdf"
    resume.write_text("hand edited")
    letter.write_text("hand edited")

    with pytest.raises(GuardError, match="Already locked.*Cover-Letter"):
        lock_application(folder, config, DAY, resume_file=resume, letter_file=letter)

    assert (folder / "First-Last-Resume.pdf").read_text() == "generated First-Last-Resume.pdf"
    assert ats_runs == []


def test_missing_pdf_is_reported_before_the_ats_run(config, folder, ats_runs):
    (folder / "First-Last-Resume.pdf").unlink()

    with pytest.raises(GuardError, match="missing in .*: First-Last-Resume.pdf"):
        lock_application(folder, config, DAY)

    assert ats_runs == []


def save_one_application(config: Config) -> None:
    acme = Application(
        id=1,
        company="Acme Health",
        role="Software Engineer",
        folder=FOLDER,
    )
    save_tracker(Tracker(applications=[acme]), config)


def test_update_applied_locks_and_records(config, folder, ats_runs):
    save_one_application(config)

    result = CliRunner().invoke(app, ["update", "Acme Health", "applied", "--date", "2026-11-21"])

    assert result.exit_code == 0, result.output
    assert "Locked applied files. ATS PASS" in result.output
    assert is_locked(folder / "resume.md")
    saved = load_tracker(workbook_path(config.data_root))
    assert saved.applications[0].stages == {Stage.APPLIED: DAY}
    assert (folder / "timeline.md").read_text().endswith("- 2026-11-21 Applied\n")


def test_nothing_is_locked_when_the_workbook_cannot_be_saved(config, folder, ats_runs):
    save_one_application(config)
    excel_lock_file(workbook_path(config.data_root)).write_text("")

    result = CliRunner().invoke(app, ["update", "Acme Health", "applied"])

    assert result.exit_code == 1
    assert "open in Excel" in result.output
    assert not is_locked(folder / "resume.md")
    assert not (folder / "timeline.md").exists()


def test_applied_without_folder_warns(config, ats_runs):
    save_one_application(config)

    result = CliRunner().invoke(app, ["update", "Acme Health", "applied"])

    assert result.exit_code == 0, result.output
    assert "no files were locked" in result.output
    assert ats_runs == []


def test_handover_files_need_applied(config, tmp_path):
    handed = tmp_path / "edited.pdf"
    handed.write_text("")

    result = CliRunner().invoke(app, ["update", "Acme", "1st", "--resume-file", str(handed)])

    assert result.exit_code == 1
    assert "only go with Applied" in result.output
