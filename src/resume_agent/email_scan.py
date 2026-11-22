import fcntl
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from resume_agent.application_folder import format_id
from resume_agent.config import Config
from resume_agent.data_root import STATE_DIR
from resume_agent.gmail import WHITESPACE, Email, Mailbox
from resume_agent.prompts import PromptError, parse_json_reply, render_prompt, text_value
from resume_agent.stages import Ambiguous, StageError, find_application, pick_line, save_stage
from resume_agent.tracker import Application, Stage, Tracker

MAX_EMAIL_CHARACTERS = 8_000
PENDING_FILE = Path(STATE_DIR, "pending-updates.json")
PENDING_LOCK = Path(STATE_DIR, "pending-updates.lock")
SCAN_STATE_FILE = Path(STATE_DIR, "gmail-scan.json")
SCAN_LOCK = Path(STATE_DIR, "gmail-scan.lock")
SCAN_QUERY = "in:inbox -category:promotions -category:social"
FIRST_SCAN_DAYS = 30
MAX_DISPLAY_CHARACTERS = 80
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SCAN_OVERLAP = timedelta(days=1)
MAX_SEEN_IDS = 1_000
ROUNDS = (Stage.APPLIED, Stage.FIRST, Stage.SECOND, Stage.THIRD)
NOTIFICATION_TITLE = "Resume Agent"
NOTIFY_SCRIPT = (
    "on run argv",
    "display notification (item 1 of argv) with title (item 2 of argv)",
    "end run",
)


class ScanError(Exception):
    pass


class EmailKind(StrEnum):
    REJECTION = "rejection"
    INTERVIEW = "interview"
    OFFER = "offer"
    OTHER = "other"


@dataclass(frozen=True)
class Classification:
    kind: EmailKind
    company: str
    role: str
    interview_date: date | None


def iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def classify_email(run: Callable[[str], str], email: Email) -> Classification:
    prompt = render_prompt(
        "classify-email",
        received=email.received.isoformat(),
        sender=email.sender,
        subject=email.subject,
        body=email.text[:MAX_EMAIL_CHARACTERS],
    )
    data = parse_json_reply(run(prompt))
    try:
        kind = EmailKind(data.get("kind"))
    except ValueError as error:
        raise PromptError(f"Unknown email kind from the model: {data.get('kind')!r}") from error
    return Classification(
        kind=kind,
        company=text_value(data.get("company")),
        role=text_value(data.get("role")),
        interview_date=iso_date(data.get("interview_date"))
        if kind == EmailKind.INTERVIEW
        else None,
    )


@dataclass
class PendingUpdate:
    number: int
    message_id: str
    received: date
    sender: str
    subject: str
    kind: EmailKind
    company: str
    role: str
    interview_date: date | None = None
    application_id: int | None = None
    candidates: list[int] = field(default_factory=list)

    @property
    def note(self) -> str:
        interview = f", interview {self.interview_date}" if self.interview_date else ""
        return f'{self.kind.value} email "{display_text(self.subject)}"{interview}'

    @property
    def source(self) -> str:
        return display_text(self.company or self.sender)


def display_text(text: str) -> str:
    cleaned = WHITESPACE.sub(" ", CONTROL_CHARACTERS.sub(" ", text)).strip()
    if len(cleaned) <= MAX_DISPLAY_CHARACTERS:
        return cleaned
    return f"{cleaned[: MAX_DISPLAY_CHARACTERS - 3].rstrip()}..."


@dataclass
class ScanState:
    last_scan: datetime | None = None
    seen: list[str] = field(default_factory=list)


def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ScanError(f"{path} is not valid JSON: {error}") from error


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(json.dumps(data, indent=2))
    os.replace(partial, path)


def update_record(update: PendingUpdate) -> dict:
    return {
        **asdict(update),
        "received": update.received.isoformat(),
        "interview_date": update.interview_date.isoformat() if update.interview_date else None,
    }


def update_from_record(record: dict) -> PendingUpdate:
    return PendingUpdate(
        **{
            **record,
            "kind": EmailKind(record["kind"]),
            "received": date.fromisoformat(record["received"]),
            "interview_date": iso_date(record["interview_date"]),
        }
    )


@contextmanager
def file_lock(path: Path, wait: bool = True) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ScanError("Another Gmail scan is running.") from error
        yield


def read_queue(data_root: Path) -> tuple[list[PendingUpdate], int]:
    path = data_root / PENDING_FILE
    data = read_json(path) or {}
    try:
        updates = [update_from_record(record) for record in data.get("updates", [])]
        next_number = int(data.get("next_number", 1))
    except (KeyError, TypeError, ValueError) as error:
        raise ScanError(f"{path} has a malformed update: {error}") from error
    return updates, max(next_number, *(update.number + 1 for update in updates), 1)


def write_queue(data_root: Path, updates: list[PendingUpdate], next_number: int) -> None:
    write_json(
        data_root / PENDING_FILE,
        {
            "next_number": next_number,
            "updates": [update_record(update) for update in updates],
        },
    )


def load_pending(data_root: Path) -> list[PendingUpdate]:
    return read_queue(data_root)[0]


def queue_update(data_root: Path, update: PendingUpdate) -> PendingUpdate:
    with file_lock(data_root / PENDING_LOCK):
        updates, next_number = read_queue(data_root)
        numbered = replace(update, number=next_number)
        write_queue(data_root, [*updates, numbered], next_number + 1)
    return numbered


def discard_pending(data_root: Path, numbers: list[int]) -> list[PendingUpdate]:
    with file_lock(data_root / PENDING_LOCK):
        updates, next_number = read_queue(data_root)
        discarded = [pending_update(updates, number) for number in dict.fromkeys(numbers)]
        kept = [update for update in updates if update not in discarded]
        write_queue(data_root, kept, next_number)
    return discarded


def load_scan_state(data_root: Path) -> ScanState:
    path = data_root / SCAN_STATE_FILE
    data = read_json(path) or {}
    last_scan = data.get("last_scan")
    try:
        return ScanState(
            last_scan=datetime.fromisoformat(last_scan) if last_scan else None,
            seen=list(data.get("seen", [])),
        )
    except (TypeError, ValueError) as error:
        raise ScanError(f"{path} is malformed: {error}") from error


def save_scan_state(data_root: Path, state: ScanState) -> None:
    write_json(
        data_root / SCAN_STATE_FILE,
        {
            "last_scan": state.last_scan.isoformat() if state.last_scan else None,
            "seen": state.seen[-MAX_SEEN_IDS:],
        },
    )


def proposed_stage(kind: EmailKind, application: Application) -> Stage | None:
    if kind == EmailKind.REJECTION:
        return Stage.REJECTED
    if kind == EmailKind.OFFER:
        return Stage.OFFER
    reached = [stage for stage in ROUNDS if stage in application.stages] or [Stage.APPLIED]
    following = ROUNDS.index(reached[-1]) + 1
    return ROUNDS[following] if following < len(ROUNDS) else None


def match_application(
    tracker: Tracker,
    classification: Classification,
    variants: dict[str, str],
) -> tuple[int | None, list[int]]:
    try:
        application = find_application(
            tracker, classification.company, variants, classification.role or None
        )
    except Ambiguous as ambiguous:
        return None, [candidate.id for candidate in ambiguous.candidates]
    except StageError:
        return None, []
    return application.id, []


def propose_update(
    email: Email,
    classification: Classification,
    tracker: Tracker,
    variants: dict[str, str],
) -> PendingUpdate | None:
    if classification.kind == EmailKind.OTHER:
        return None
    application_id, candidates = match_application(tracker, classification, variants)
    return PendingUpdate(
        number=0,
        message_id=email.id,
        received=email.received,
        sender=email.sender,
        subject=email.subject,
        kind=classification.kind,
        company=classification.company,
        role=classification.role,
        interview_date=classification.interview_date,
        application_id=application_id,
        candidates=candidates,
    )


def classify_or_skip(
    run: Callable[[str], str],
    email: Email,
    report: Callable[[str], None],
) -> Classification | None:
    try:
        return classify_email(run, email)
    except PromptError as error:
        report(f"Skipped {email.received} {display_text(email.subject)}: {error}")
        return None


def scan_query(last_scan: datetime | None) -> str:
    if not last_scan:
        return f"{SCAN_QUERY} newer_than:{FIRST_SCAN_DAYS}d"
    return f"{SCAN_QUERY} after:{int((last_scan - SCAN_OVERLAP).timestamp())}"


def scan_mailbox(
    mailbox: Mailbox,
    tracker: Tracker,
    variants: dict[str, str],
    run: Callable[[str], str],
    data_root: Path,
    now: datetime,
    report: Callable[[str], None],
) -> list[PendingUpdate]:
    with file_lock(data_root / SCAN_LOCK, wait=False):
        state = load_scan_state(data_root)
        known = {*state.seen, *(update.message_id for update in load_pending(data_root))}
        oldest_first = reversed(mailbox.message_ids(scan_query(state.last_scan)))
        added = []
        for message_id in [message_id for message_id in oldest_first if message_id not in known]:
            email = mailbox.message(message_id)
            classification = classify_or_skip(run, email, report)
            update = classification and propose_update(email, classification, tracker, variants)
            if update:
                added.append(queue_update(data_root, update))
            state.seen.append(message_id)
            save_scan_state(data_root, state)
        state.last_scan = now
        save_scan_state(data_root, state)
    return added


def target_line(update: PendingUpdate, tracker: Tracker) -> str:
    if update.application_id is None:
        if update.candidates:
            return f"pick one of {', '.join(format_id(app_id) for app_id in update.candidates)}"
        return "no open application matched"
    try:
        application = find_application(tracker, "", {}, application_id=update.application_id)
    except StageError as error:
        return str(error)
    stage = proposed_stage(update.kind, application)
    return f"{pick_line(application)}: {stage.value if stage else 'no round after 3rd'}"


def describe_update(update: PendingUpdate, tracker: Tracker) -> str:
    return (
        f"{update.number}. {update.received} {update.source} {update.kind.value}"
        f" → {target_line(update, tracker)}"
    )


def pending_update(pending: list[PendingUpdate], number: int) -> PendingUpdate:
    found = next((update for update in pending if update.number == number), None)
    if found is None:
        raise ScanError(f"No pending update {number}. List them with `resume_agent updates`.")
    return found


def confirm_update(
    update: PendingUpdate,
    tracker: Tracker,
    config: Config,
    application_id: int | None = None,
) -> tuple[Application, Stage]:
    chosen = update.application_id if application_id is None else application_id
    if chosen is None:
        raise ScanError(f"{describe_update(update, tracker)}\nRerun with --id <ID>.")
    application = find_application(tracker, "", {}, application_id=chosen)
    stage = proposed_stage(update.kind, application)
    if stage is None:
        raise StageError(
            f"{pick_line(application)} already had a 3rd round. "
            "Record Offer or Rejected with `resume_agent update`."
        )
    save_stage(tracker, application, stage, update.received, config, update.note)
    return application, stage


def notification(added: list[PendingUpdate]) -> str:
    if len(added) > 1:
        return f"{len(added)} email updates to confirm"
    update = added[0]
    matched = update.application_id is not None
    target = f"#{format_id(update.application_id)}" if matched else "which application"
    return f"{update.source} {update.kind.value} → {target}?"


def notify(message: str) -> None:
    script = [argument for line in NOTIFY_SCRIPT for argument in ("-e", line)]
    try:
        subprocess.run(
            ["osascript", *script, message, NOTIFICATION_TITLE],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass
