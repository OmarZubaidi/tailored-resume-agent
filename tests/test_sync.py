from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent import pipeline
from resume_agent.application_folder import (
    add_timeline_event,
    has_timeline_event,
    remove_timeline_event,
)
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.guards.rules import is_locked
from resume_agent.pipeline import applied_files
from resume_agent.sync import SYNC_LOCK, SyncError, sync_lock, sync_stages
from resume_agent.tracker import Application, Stage, Tracker, save_tracker

FOLDER = "00001 Acme Health - Software Engineer (2026-11-20)"
APPLIED = date(2026, 11, 20)
REJECTED = date(2026, 11, 28)
TODAY = date(2026, 11, 30)


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


@pytest.fixture(autouse=True)
def skip_ats(monkeypatch):
    monkeypatch.setattr(pipeline, "write_ats_report", lambda folder, config: True)


def tracker(**stages: date) -> Tracker:
    return Tracker(
        applications=[
            Application(
                id=1,
                company="Acme Health",
                role="Software Engineer",
                folder=FOLDER,
                stages={Stage(name): day for name, day in stages.items()},
            )
        ]
    )


def timeline(folder: Path) -> str:
    return (folder / "timeline.md").read_text()


def locked(folder: Path, config: Config) -> bool:
    return all(is_locked(folder / name) for name in applied_files(config))


def test_timeline_event_matches_with_or_without_a_note(tmp_path):
    add_timeline_event(tmp_path, APPLIED, "2nd: technical Dec 10")
    add_timeline_event(tmp_path, APPLIED, "2nd round prep")

    assert has_timeline_event(tmp_path, APPLIED, "2nd")
    remove_timeline_event(tmp_path, APPLIED, "2nd")
    assert timeline(tmp_path) == "# Timeline\n\n- 2026-11-20 2nd round prep\n"


def test_applied_date_adds_timeline_and_locks(config, folder):
    result = sync_stages(tracker(Applied=APPLIED), config, TODAY)

    assert result.events == [
        "00001  Acme Health - Software Engineer (applied 2026-11-20): Applied 2026-11-20, "
        "files locked"
    ]
    assert "- 2026-11-20 Applied\n" in timeline(folder)
    assert locked(folder, config)


def test_unchanged_sheet_does_nothing(config, folder):
    sync_stages(tracker(Applied=APPLIED), config, TODAY)

    assert sync_stages(tracker(Applied=APPLIED), config, TODAY).events == []
    assert timeline(folder).count("Applied") == 1


def test_cleared_date_is_undone(config, folder):
    sync_stages(tracker(Applied=APPLIED), config, TODAY)

    result = sync_stages(tracker(), config, TODAY)

    assert "Applied 2026-11-20 cleared, files unlocked" in result.events[0]
    assert "Applied" not in timeline(folder)
    assert not any(is_locked(folder / name) for name in applied_files(config))
    assert "unlocked `resume.md`" in (folder / "notes.md").read_text()


def test_rejection_before_applying_locks(config, folder):
    sync_stages(tracker(Rejected=REJECTED), config, TODAY)

    assert locked(folder, config)


def test_clearing_rejected_keeps_applied_lock(config, folder):
    sync_stages(tracker(Applied=APPLIED, Rejected=REJECTED), config, TODAY)

    sync_stages(tracker(Applied=APPLIED), config, TODAY)

    assert locked(folder, config)
    assert "Rejected" not in timeline(folder)


def test_changed_date_moves_the_timeline_line(config, folder):
    sync_stages(tracker(Applied=APPLIED), config, TODAY)

    sync_stages(tracker(Applied=date(2026, 11, 21)), config, TODAY)

    assert "2026-11-20" not in timeline(folder)
    assert "- 2026-11-21 Applied\n" in timeline(folder)


def test_stage_recorded_by_update_is_not_doubled(config, folder):
    add_timeline_event(folder, REJECTED, "Rejected: after phone screen")

    sync_stages(tracker(Rejected=REJECTED), config, TODAY)

    assert timeline(folder).count("Rejected") == 1


def test_dropped_job_without_documents_is_fine(config):
    (config.data_root / "applications" / FOLDER).mkdir(parents=True)

    result = sync_stages(tracker(Skipped=TODAY), config, TODAY)

    assert result.failures == []


def test_missing_document_is_reported_and_retried(config, folder):
    (folder / "resume.md").unlink()

    first = sync_stages(tracker(Applied=APPLIED), config, TODAY)
    second = sync_stages(tracker(Applied=APPLIED), config, TODAY)

    assert "missing" in first.failures[0]
    assert second.failures == first.failures


def test_application_without_folder_is_recorded(config):
    result = sync_stages(tracker(Applied=APPLIED), config, TODAY)

    assert result.failures == []
    assert result.events[0].endswith("Applied 2026-11-20")


def test_overlapping_sync_is_refused(config):
    with sync_lock(config.data_root):
        with pytest.raises(SyncError, match="Another sync is running"):
            sync_stages(tracker(), config, TODAY)
    assert (config.data_root / SYNC_LOCK).exists()


def test_sync_command_reads_the_workbook(config, folder):
    save_tracker(tracker(Applied=APPLIED), config)

    result = CliRunner().invoke(app, ["sync"])

    assert result.exit_code == 0, result.output
    assert "Applied 2026-11-20, files locked" in result.output
    assert locked(folder, config)
