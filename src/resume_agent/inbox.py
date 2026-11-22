from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from resume_agent.application_folder import (
    add_timeline_event,
    folder_name,
    move_folder,
    next_id,
)
from resume_agent.browser import BrowserError
from resume_agent.config import Config
from resume_agent.data_root import APPLICATIONS_DIR
from resume_agent.documents import DocumentError
from resume_agent.job_listing import LISTING_MD, ListingError, fetch_listing, read_listing
from resume_agent.ledger import LedgerError
from resume_agent.llm import LlmError
from resume_agent.pipeline import Mode, baseline_dir, tailor_folder, triage_folder
from resume_agent.prompts import PromptError
from resume_agent.render import RenderError
from resume_agent.tailor import TailorError
from resume_agent.tracker import MODES, Application, InboxRow, Tracker
from resume_agent.validation import resolve_listing

FLAGGED = "flagged"
FAILED = "error"
PENDING_STATUSES = ("", FAILED)
STAGING_DIR = Path(".state/inbox")


class InboxError(Exception):
    pass


ROW_ERRORS = (
    BrowserError,
    DocumentError,
    FileNotFoundError,
    InboxError,
    LedgerError,
    ListingError,
    LlmError,
    PromptError,
    RenderError,
    TailorError,
)


@dataclass
class InboxResult:
    tailored: list[Application] = field(default_factory=list)
    flagged: list[InboxRow] = field(default_factory=list)
    failed: list[InboxRow] = field(default_factory=list)


def check_row(row: InboxRow, config: Config) -> None:
    if row.mode and row.mode not in MODES:
        raise InboxError(f"Mode {row.mode!r} must be one of: {', '.join(MODES)}")
    if row.baseline and not baseline_dir(config, row.baseline).is_dir():
        raise InboxError(f"No baseline named {row.baseline!r}")


def staging_folder(config: Config, application_id: int) -> Path:
    folder = config.data_root / STAGING_DIR / str(application_id)
    folder.mkdir(parents=True, exist_ok=True)
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
    if (staging / LISTING_MD).exists():
        listing = read_listing(staging / LISTING_MD)
    else:
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
) -> InboxResult:
    result = InboxResult()
    pending = [row for row in tracker.inbox if row.url and row.status in PENDING_STATUSES]
    for row in pending:
        report(f"Processing {row.url}")
        try:
            check_row(row, config)
            if not row.folder:
                triage_row(row, tracker, config, run, today, save)
            if row.status != FLAGGED:
                result.tailored.append(tailor_row(row, tracker, config, run, today))
        except ROW_ERRORS as error:
            row.status = FAILED
            row.reason = str(error)
            result.failed.append(row)
        save()
    result.flagged = [row for row in tracker.inbox if row.status == FLAGGED]
    return result
