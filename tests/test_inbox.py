import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from resume_agent import cli, inbox
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.guards.rules import excel_lock_file
from resume_agent.inbox import FAILED, FLAGGED, process_inbox, sync_inbox
from resume_agent.job_listing import Listing, ListingError, save_listing
from resume_agent.notify import SYNC_STOPPED
from resume_agent.pipeline import Mode
from resume_agent.sync import SYNC_STATE, SyncResult
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
    assert "typing proceed or drop in the Decision column" in result.output


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


def sync(tracker: Tracker, config: Config, reports: list[str] | None = None):
    saves = []

    def save() -> None:
        saves.append(True)
        save_tracker(tracker, config, TODAY)

    result = sync_inbox(
        tracker,
        config,
        fake_llm,
        TODAY,
        save=save,
        report=(reports if reports is not None else []).append,
    )
    return result, saves


def test_decisions_proceed_and_drop_flagged_rows(config, calls, monkeypatch):
    other = "https://jobs.example.com/globex/3"
    staff = ("Globex", "Staff Engineer", "Remote. TS/SCI clearance required.")
    monkeypatch.setitem(LISTINGS, other, staff)
    tracker = Tracker(inbox=[InboxRow(url=FLAGGED_URL), InboxRow(url=other)])
    run(tracker, config)
    tracker.inbox[0].decision = "proceed"
    tracker.inbox[1].decision = "drop"

    result, _ = sync(tracker, config)

    assert tracker.inbox == []
    assert [app.status for app in result.tailored] == ["Interested", "Skipped"]


def test_failed_rows_wait_for_proceed(config, calls, monkeypatch):
    tracker = Tracker(inbox=[InboxRow(url=CLEAR_URL, status=FAILED, reason="timeout")])

    untouched, saves = sync(tracker, config)
    tracker.inbox[0].decision = "proceed"
    retried, _ = sync(tracker, config)

    assert untouched.tailored == [] and saves == []
    assert calls["fetch"] == [CLEAR_URL]
    assert retried.tailored[0].company == "Acme Health"


def test_new_rows_are_processed_and_nothing_waiting_saves_nothing(config, calls):
    tracker = Tracker(inbox=[InboxRow(url=CLEAR_URL)])

    first, _ = sync(tracker, config)
    second, saves = sync(tracker, config)

    assert len(first.tailored) == 1
    assert second.tailored == [] and saves == []


@pytest.mark.parametrize(
    ("status", "decision", "reason"),
    [
        (FAILED, "drop", "needs a flagged or failed row"),
        (FLAGGED, "procede", "must be one of: proceed, drop"),
    ],
)
def test_unusable_decision_stays_in_its_cell(config, calls, status, decision, reason):
    tracker = Tracker(inbox=[InboxRow(url=CLEAR_URL, id=1, status=status, decision=decision)])
    reports = []

    _, saves = sync(tracker, config, reports)

    assert reports == [
        f"Decision {decision!r} for {CLEAR_URL} {reason}. Left in the Decision cell."
    ]
    assert tracker.inbox[0].decision == decision
    assert saves == []


def test_sync_command_leaves_the_inbox_while_excel_is_open(config, calls, monkeypatch):
    monkeypatch.setattr(cli, "run_prompt", lambda _, prompt: fake_llm(prompt))
    save_tracker(Tracker(inbox=[InboxRow(url=CLEAR_URL)]), config)
    lock = excel_lock_file(workbook_path(config.data_root))
    lock.write_text("")

    open_run = CliRunner().invoke(app, ["sync"])
    lock.unlink()
    closed_run = CliRunner().invoke(app, ["sync"])

    assert "Excel is open; the Inbox waits until it closes." in open_run.output
    assert closed_run.exit_code == 0, closed_run.output
    assert "Interested: 00001  Acme Health - Software Engineer" in closed_run.output
    assert load_tracker(workbook_path(config.data_root)).inbox == []


def test_sync_command_notifies_failed_and_flagged_rows(config, calls, monkeypatch, notifications):
    monkeypatch.setattr(cli, "run_prompt", lambda _, prompt: fake_llm(prompt))
    rows = [
        InboxRow(url=CLEAR_URL),
        InboxRow(url=FLAGGED_URL),
        InboxRow(url="https://jobs.example.com/initech/3"),
    ]
    save_tracker(Tracker(inbox=rows), config)

    result = CliRunner().invoke(app, ["sync"])

    assert result.exit_code == 1
    assert notifications == ["1 failed, 1 waiting for review. See sync.log."]


def test_sync_command_notifies_stage_failures(config, monkeypatch, notifications):
    monkeypatch.setattr(cli, "sync_stages", lambda *_: SyncResult(failures=["00001: locked"]))
    save_tracker(Tracker(), config)

    result = CliRunner().invoke(app, ["sync"])

    assert result.exit_code == 1
    assert notifications == ["1 failed. See sync.log."]


def test_sync_command_that_stops_notifies(config, notifications):
    save_tracker(Tracker(), config)
    (config.data_root / SYNC_STATE).write_text("not json")

    result = CliRunner().invoke(app, ["sync"])

    assert result.exit_code == 1
    assert notifications == [SYNC_STOPPED]


def test_sync_command_without_problems_sends_no_notification(config, calls, notifications):
    save_tracker(Tracker(), config)

    result = CliRunner().invoke(app, ["sync"])

    assert result.exit_code == 0, result.output
    assert notifications == []


def test_review_rejects_ids_that_are_not_flagged(config, calls):
    save_tracker(Tracker(inbox=[InboxRow(url=CLEAR_URL)]), config)

    result = CliRunner().invoke(app, ["review", "drop", "7"])

    assert result.exit_code == 1
    assert "No flagged Inbox row with ID 00007" in result.output
