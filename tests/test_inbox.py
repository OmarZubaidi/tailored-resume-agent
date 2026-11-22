import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from resume_agent import cli, inbox
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.inbox import FAILED, FLAGGED, process_inbox
from resume_agent.job_listing import Listing, ListingError, save_listing
from resume_agent.pipeline import Mode
from resume_agent.tailor import TailorError
from resume_agent.tracker import InboxRow, Tracker, load_tracker, save_tracker, workbook_path

TODAY = date(2026, 11, 21)
CLEAR_URL = "https://jobs.example.com/acme/1"
FLAGGED_URL = "https://jobs.example.com/globex/2"
LISTINGS = {
    CLEAR_URL: ("Acme Health", "Software Engineer", "Remote. Build things."),
    FLAGGED_URL: ("Globex", "Platform Engineer", "Remote. Active security clearance required."),
}


@pytest.fixture
def config(config_data, write_config, data_root) -> Config:
    (data_root / "baselines/general").mkdir(parents=True)
    (data_root / ".state").mkdir()
    write_config(config_data)
    return Config(**config_data)


@pytest.fixture
def calls(monkeypatch) -> dict[str, list]:
    calls = {
        "fetch": [],
        "tailor": [],
    }

    def fake_fetch(url: str, out_dir: Path) -> Listing:
        calls["fetch"].append(url)
        if url not in LISTINGS:
            raise ListingError(f"Could not load {url}")
        _, role, text = LISTINGS[url]
        return save_listing(Listing(source=url, title=role, text=text), out_dir)

    def fake_tailor(folder, config, run, baseline, mode):
        calls["tailor"].append(folder.name)
        (folder / "resume.md").write_text("tailored")
        return SimpleNamespace(
            mode=mode or Mode.LATERAL,
            flags=["check wording"],
            render=SimpleNamespace(passed=True),
        )

    monkeypatch.setattr(inbox, "fetch_listing", fake_fetch)
    monkeypatch.setattr(inbox, "resolve_listing", lambda raw, out_dir: (raw, None, False))
    monkeypatch.setattr(inbox, "tailor_folder", fake_tailor)
    return calls


def fake_llm(prompt: str) -> str:
    company, role = next(
        (company, role) for company, role, text in LISTINGS.values() if text in prompt
    )
    return json.dumps(
        {
            "company": company,
            "role": role,
            "years_required": None,
            "required_skills": [],
            "other_requirements": [],
        }
    )


def run(tracker: Tracker, config: Config):
    return process_inbox(
        tracker,
        config,
        fake_llm,
        TODAY,
        save=lambda: save_tracker(tracker, config, TODAY),
        report=lambda _: None,
    )


def test_clear_row_is_tailored_and_moved(config, calls):
    tracker = Tracker(inbox=[InboxRow(url=CLEAR_URL, mode="upward")])

    result = run(tracker, config)

    assert tracker.inbox == []
    [application] = tracker.applications
    assert application == result.tailored[0]
    assert (application.id, application.company, application.role) == (
        1,
        "Acme Health",
        "Software Engineer",
    )
    assert application.folder == "00001 Acme Health - Software Engineer (2026-11-21)"
    assert (application.mode, application.baseline, application.link) == (
        "upward",
        "general",
        CLEAR_URL,
    )
    assert application.notes == "1 items to review in diff.md"
    folder = config.data_root / "applications" / application.folder
    assert (folder / "listing.md").exists()
    assert (folder / "triage.md").exists()
    assert "Tailored (upward, general)" in (folder / "timeline.md").read_text()
    assert not (config.data_root / ".state/inbox/1").exists()
    assert load_tracker(workbook_path(config.data_root)) == tracker


def test_flagged_row_waits_in_inbox(config, calls):
    tracker = Tracker(inbox=[InboxRow(url=FLAGGED_URL), InboxRow(url=CLEAR_URL)])

    result = run(tracker, config)

    [row] = tracker.inbox
    assert row.status == FLAGGED
    assert (row.id, row.company, row.role) == (1, "Globex", "Platform Engineer")
    assert row.reason.startswith("Clearance:")
    assert result.flagged == [row]
    assert calls["tailor"] == ["00002 Acme Health - Software Engineer (2026-11-21)"]


def test_failed_fetch_does_not_stop_the_batch_and_retries(config, calls, monkeypatch):
    bad_url = "https://jobs.example.com/missing"
    tracker = Tracker(inbox=[InboxRow(url=bad_url), InboxRow(url=CLEAR_URL)])

    result = run(tracker, config)

    assert [row.url for row in result.failed] == [bad_url]
    assert tracker.inbox[0].status == FAILED
    assert tracker.inbox[0].reason == f"Could not load {bad_url}"
    assert [app.id for app in tracker.applications] == [2]

    monkeypatch.setitem(LISTINGS, bad_url, ("Initech", "Engineer", "Remote."))
    run(tracker, config)

    assert tracker.inbox == []
    assert sorted(app.id for app in tracker.applications) == [1, 2]


def test_failed_tailor_resumes_without_refetching(config, calls, monkeypatch):
    tracker = Tracker(inbox=[InboxRow(url=CLEAR_URL)])
    real_tailor = inbox.tailor_folder

    def broken_tailor(*args):
        raise TailorError(["plan invented a number"])

    monkeypatch.setattr(inbox, "tailor_folder", broken_tailor)
    run(tracker, config)
    [row] = tracker.inbox
    assert row.status == FAILED
    assert "plan invented a number" in row.reason
    assert row.folder

    monkeypatch.setattr(inbox, "tailor_folder", real_tailor)
    run(tracker, config)

    assert calls["fetch"] == [CLEAR_URL]
    assert [app.id for app in tracker.applications] == [1]


def test_listing_that_failed_validation_is_refetched(config, calls, monkeypatch):
    def login_wall(raw, out_dir):
        raise ListingError("Looks like a login page")

    monkeypatch.setattr(inbox, "resolve_listing", login_wall)
    tracker = Tracker(inbox=[InboxRow(url=CLEAR_URL)])
    run(tracker, config)
    assert tracker.inbox[0].reason == "Looks like a login page"

    monkeypatch.setattr(inbox, "resolve_listing", lambda raw, out_dir: (raw, None, False))
    run(tracker, config)

    assert calls["fetch"] == [CLEAR_URL, CLEAR_URL]
    assert [app.id for app in tracker.applications] == [1]


def test_bad_mode_and_baseline_fail_the_row(config, calls):
    tracker = Tracker(
        inbox=[
            InboxRow(
                url=CLEAR_URL,
                mode="sideways",
            ),
            InboxRow(
                url=FLAGGED_URL,
                baseline="missing",
            ),
        ]
    )

    result = run(tracker, config)

    assert [row.reason for row in result.failed] == [
        "Mode 'sideways' must be one of: upward, lateral",
        "No baseline named 'missing'",
    ]
    assert calls["fetch"] == []


def test_inbox_command_lists_flagged_jobs(config, calls, monkeypatch):
    monkeypatch.setattr(cli, "run_prompt", lambda _, prompt: fake_llm(prompt))
    save_tracker(Tracker(inbox=[InboxRow(url=FLAGGED_URL)]), config)

    result = CliRunner().invoke(app, ["inbox"])

    assert result.exit_code == 0, result.output
    assert "00001  Globex - Platform Engineer: Clearance:" in result.output
    assert "resume_agent review proceed|drop <ID>..." in result.output


@pytest.fixture
def fixed_today(monkeypatch) -> None:
    monkeypatch.setattr(cli, "today", lambda: TODAY)


def test_review_proceed_tailors_and_drop_skips(config, calls, monkeypatch, fixed_today):
    monkeypatch.setattr(cli, "run_prompt", lambda _, prompt: fake_llm(prompt))
    other = "https://jobs.example.com/globex/3"
    staff = ("Globex", "Staff Engineer", "Remote. TS/SCI clearance required.")
    monkeypatch.setitem(LISTINGS, other, staff)
    run(Tracker(inbox=[InboxRow(url=FLAGGED_URL), InboxRow(url=other)]), config)

    proceed = CliRunner().invoke(app, ["review", "proceed", "1"])
    drop = CliRunner().invoke(app, ["review", "drop", "2"])

    assert proceed.exit_code == 0, proceed.output
    assert "Interested: 00001  Globex - Platform Engineer" in proceed.output
    assert drop.exit_code == 0, drop.output
    assert "Skipped: 00002  Globex - Staff Engineer" in drop.output
    saved = load_tracker(workbook_path(config.data_root))
    assert saved.inbox == []
    assert [app.status for app in saved.applications] == ["Interested", "Skipped"]
    skipped_folder = config.data_root / "applications" / saved.applications[1].folder
    assert (skipped_folder / "timeline.md").read_text().endswith("- 2026-11-21 Skipped\n")


def test_review_ignores_repeated_ids(config, calls, fixed_today):
    run(Tracker(inbox=[InboxRow(url=FLAGGED_URL)]), config)

    result = CliRunner().invoke(app, ["review", "drop", "1", "1"])

    assert result.exit_code == 0, result.output
    folder = config.data_root / "applications/00001 Globex - Platform Engineer (2026-11-21)"
    assert (folder / "timeline.md").read_text().count("Skipped") == 1


def test_review_rejects_ids_that_are_not_flagged(config, calls):
    save_tracker(Tracker(inbox=[InboxRow(url=CLEAR_URL)]), config)

    result = CliRunner().invoke(app, ["review", "drop", "7"])

    assert result.exit_code == 1
    assert "No flagged Inbox row with ID 00007" in result.output
