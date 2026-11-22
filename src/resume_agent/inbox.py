import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from resume_agent.application_folder import (
    add_timeline_event,
    folder_name,
    format_id,
    move_folder,
    next_id,
)
from resume_agent.config import Config
from resume_agent.data_root import APPLICATIONS_DIR, STATE_DIR
from resume_agent.job_listing import ListingError, fetch_listing
from resume_agent.pipeline import TAILOR_ERRORS, Mode, baseline_dir, tailor_folder, triage_folder
from resume_agent.tracker import MODES, Application, Decision, InboxRow, Stage, Tracker
from resume_agent.validation import resolve_listing

FLAGGED = "flagged"
FAILED = "error"
PENDING_STATUSES = ("", FAILED)
STAGING_DIR = Path(STATE_DIR, "inbox")


class InboxError(Exception):
    pass


ROW_ERRORS = (*TAILOR_ERRORS, InboxError, ListingError, OSError)


@dataclass
class InboxResult:
    tailored: list[Application] = field(default_factory=list)
    flagged: list[InboxRow] = field(default_factory=list)
    failed: list[InboxRow] = field(default_factory=list)


def fail_row(row: InboxRow, error: Exception, result: InboxResult) -> None:
    row.status = FAILED
    row.reason = str(error)
    result.failed.append(row)


def check_row(row: InboxRow, config: Config) -> None:
    if row.mode and row.mode not in MODES:
        raise InboxError(f"Mode {row.mode!r} must be one of: {', '.join(MODES)}")
    if row.baseline and not baseline_dir(config, row.baseline).is_dir():
        raise InboxError(f"No baseline named {row.baseline!r}")


def staging_folder(config: Config, application_id: int) -> Path:
    folder = config.data_root / STAGING_DIR / str(application_id)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def triage_row(
    row: InboxRow,
    tracker: Tracker,
    config: Config,
    run: Callable[[str], str],
    today: date,
    save: Callable[[], None],
) -> Path:
    if row.id is None:
        row.id = next_id(tracker)
        save()
    staging = staging_folder(config, row.id)
    listing, _, _ = resolve_listing(fetch_listing(row.url, staging), staging)
    triage = triage_folder(listing, staging, config, run, row.baseline or None)
    row.company, row.role = triage.company, triage.role
    name = folder_name(row.id, row.company, row.role, today)
    folder = move_folder(staging, config.data_root, name)
    row.folder = folder.name
    if triage.flagged:
        row.status = FLAGGED
        row.reason = "; ".join(triage.flags)
        add_timeline_event(folder, today, f"Flagged: {row.reason}")
    save()
    return folder


def tailor_row(
    row: InboxRow,
    tracker: Tracker,
    config: Config,
    run: Callable[[str], str],
    today: date,
) -> Application:
    folder = config.data_root / APPLICATIONS_DIR / row.folder
    baseline = row.baseline or config.default_baseline
    result = tailor_folder(folder, config, run, baseline, Mode(row.mode) if row.mode else None)
    notes = []
    if not result.render.passed:
        notes.append("ATS FAIL, see ats-report.md")
    if result.flags:
        notes.append(f"{len(result.flags)} items to review in diff.md")
    application = Application(
        id=row.id,
        company=row.company,
        role=row.role,
        link=row.url,
        folder=row.folder,
        mode=result.mode.value,
        baseline=baseline,
        notes="; ".join(notes),
    )
    add_timeline_event(folder, today, f"Tailored ({result.mode.value}, {baseline})")
    move_to_applications(row, application, tracker)
    return application


def skip_row(row: InboxRow, tracker: Tracker, config: Config, today: date) -> Application:
    application = Application(
        id=row.id,
        company=row.company,
        role=row.role,
        link=row.url,
        folder=row.folder,
        mode=row.mode,
        baseline=row.baseline,
        notes=row.reason,
        stages={Stage.SKIPPED: today},
    )
    add_timeline_event(config.data_root / APPLICATIONS_DIR / row.folder, today, "Skipped")
    move_to_applications(row, application, tracker)
    return application


def flagged_row(tracker: Tracker, application_id: int) -> InboxRow:
    row = next((row for row in tracker.inbox if row.id == application_id), None)
    if row is None or row.status != FLAGGED:
        raise InboxError(f"No flagged Inbox row with ID {format_id(application_id)}")
    return row


def review_rows(
    tracker: Tracker,
    application_ids: list[int],
    decision: Decision,
    config: Config,
    run: Callable[[str], str],
    today: date,
    save: Callable[[], None],
) -> InboxResult:
    unique_ids = dict.fromkeys(application_ids)
    rows = [flagged_row(tracker, application_id) for application_id in unique_ids]
    result = InboxResult()
    for row in rows:
        if decision == Decision.DROP:
            result.tailored.append(skip_row(row, tracker, config, today))
        else:
            try:
                result.tailored.append(tailor_row(row, tracker, config, run, today))
            except ROW_ERRORS as error:
                fail_row(row, error, result)
        save()
    return result


def move_to_applications(row: InboxRow, application: Application, tracker: Tracker) -> None:
    tracker.inbox.remove(row)
    tracker.applications.append(application)


def process_inbox(
    tracker: Tracker,
    config: Config,
    run: Callable[[str], str],
    today: date,
    save: Callable[[], None],
    report: Callable[[str], None],
    retry_failed: bool = True,
) -> InboxResult:
    result = InboxResult()
    statuses = PENDING_STATUSES if retry_failed else ("",)
    pending = [row for row in tracker.inbox if row.url and row.status in statuses]
    for row in pending:
        report(f"Processing {row.url}")
        try:
            check_row(row, config)
            if not row.folder:
                triage_row(row, tracker, config, run, today, save)
            if row.status != FLAGGED:
                result.tailored.append(tailor_row(row, tracker, config, run, today))
        except ROW_ERRORS as error:
            fail_row(row, error, result)
        save()
    result.flagged = [row for row in tracker.inbox if row.status == FLAGGED]
    return result


def merge_results(target: InboxResult, source: InboxResult) -> None:
    target.tailored += source.tailored
    target.failed += source.failed


def apply_decision(
    row: InboxRow,
    tracker: Tracker,
    config: Config,
    run: Callable[[str], str],
    today: date,
    save: Callable[[], None],
    result: InboxResult,
) -> None:
    decision = row.decision
    if decision not in set(Decision):
        raise InboxError(
            f"Decision {decision!r} for {row.url} must be one of: {', '.join(Decision)}"
        )
    retry = row.status == FAILED and decision == Decision.PROCEED
    if row.status != FLAGGED and not retry:
        raise InboxError(f"Decision {decision!r} for {row.url} needs a flagged or failed row")
    row.decision = ""
    if retry:
        row.status = ""
    else:
        decided = review_rows(tracker, [row.id], Decision(decision), config, run, today, save)
        merge_results(result, decided)


def sync_inbox(
    tracker: Tracker,
    config: Config,
    run: Callable[[str], str],
    today: date,
    save: Callable[[], None],
    report: Callable[[str], None],
) -> InboxResult:
    result = InboxResult()
    for row in [row for row in tracker.inbox if row.decision]:
        try:
            apply_decision(row, tracker, config, run, today, save, result)
        except InboxError as error:
            report(f"{error}. Left in the Decision cell.")
            continue
        save()
    processed = process_inbox(tracker, config, run, today, save, report, retry_failed=False)
    merge_results(result, processed)
    result.flagged = processed.flagged
    return result
