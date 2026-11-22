import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from resume_agent.application_folder import (
    add_timeline_event,
    application_dir,
    has_timeline_event,
    remove_timeline_event,
)
from resume_agent.config import Config
from resume_agent.data_root import STATE_DIR
from resume_agent.documents import DocumentError
from resume_agent.guards.rules import GuardError, is_locked, unlock_applied_files
from resume_agent.pipeline import applied_files, lock_application
from resume_agent.stages import pick_line
from resume_agent.tracker import Application, Stage, Tracker

SYNC_STATE = Path(STATE_DIR, "sync.json")
SYNC_LOCK = Path(STATE_DIR, "sync.lock")
LOCKING_STAGES = (Stage.APPLIED, Stage.REJECTED, Stage.SKIPPED)
FOLDER_ERRORS = (DocumentError, GuardError, OSError)


class SyncError(Exception):
    pass


@dataclass(frozen=True)
class StageChange:
    stage: Stage
    old: date | None
    new: date | None

    def describe(self) -> str:
        if self.new is None:
            return f"{self.stage.value} {self.old} cleared"
        return f"{self.stage.value} {self.new}"


@dataclass
class SyncResult:
    events: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@contextmanager
def sync_lock(data_root: Path) -> Iterator[None]:
    path = data_root / SYNC_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SyncError("Another sync is running.") from error
        yield


def load_seen(data_root: Path) -> dict[str, dict[str, str]]:
    path = data_root / SYNC_STATE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise SyncError(f"{path} is not valid JSON: {error}") from error
    applications = data.get("applications") if isinstance(data, dict) else None
    if not isinstance(applications, dict):
        raise SyncError(f"{path} has no applications map")
    return applications


def save_seen(data_root: Path, seen: dict[str, dict[str, str]]) -> None:
    path = data_root / SYNC_STATE
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(json.dumps({"applications": seen}, indent=2))
    os.replace(partial, path)


def stage_dates(application: Application) -> dict[str, str]:
    return {stage.value: day.isoformat() for stage, day in application.stages.items()}


def stage_changes(application: Application, before: dict[str, str]) -> list[StageChange]:
    changes = []
    for stage in Stage:
        recorded = before.get(stage.value)
        old = date.fromisoformat(recorded) if recorded else None
        new = application.stages.get(stage)
        if old != new:
            changes.append(StageChange(stage, old, new))
    return changes


def sync_timeline(folder: Path, change: StageChange) -> None:
    if change.old:
        remove_timeline_event(folder, change.old, change.stage.value)
    if change.new and not has_timeline_event(folder, change.new, change.stage.value):
        add_timeline_event(folder, change.new, change.stage.value)


def sync_locks(folder: Path, application: Application, config: Config, today: date) -> str | None:
    names = applied_files(config)
    if not any((folder / name).exists() for name in names):
        return None
    should_lock = any(stage in application.stages for stage in LOCKING_STAGES)
    if should_lock and not all(is_locked(folder / name) for name in names):
        lock_application(folder, config, today)
        return "files locked"
    if not should_lock and any(is_locked(folder / name) for name in names):
        unlock_applied_files(folder, names, today)
        return "files unlocked"
    return None


def sync_folder(
    folder: Path,
    application: Application,
    changes: list[StageChange],
    config: Config,
    today: date,
) -> list[str]:
    for change in changes:
        sync_timeline(folder, change)
    locks = sync_locks(folder, application, config, today)
    return [locks] if locks else []


def sync_stages(tracker: Tracker, config: Config, today: date) -> SyncResult:
    result = SyncResult()
    with sync_lock(config.data_root):
        seen = load_seen(config.data_root)
        for application in tracker.applications:
            key = str(application.id)
            changes = stage_changes(application, seen.get(key, {}))
            if not changes:
                continue
            details = [change.describe() for change in changes]
            folder = application_dir(config.data_root, application)
            if folder:
                try:
                    details += sync_folder(folder, application, changes, config, today)
                except FOLDER_ERRORS as error:
                    result.failures.append(f"{pick_line(application)}: {error}")
                    continue
            result.events.append(f"{pick_line(application)}: {', '.join(details)}")
            seen[key] = stage_dates(application)
            save_seen(config.data_root, seen)
    return result
