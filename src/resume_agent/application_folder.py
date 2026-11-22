import re
import shutil
from datetime import date
from pathlib import Path

from resume_agent.data_root import APPLICATIONS_DIR
from resume_agent.tracker import ID_DIGITS, Application, Tracker

TIMELINE_FILE = "timeline.md"
TIMELINE_HEADING = "# Timeline\n\n"
MAX_NAME_PART = 60
UNSAFE_CHARACTERS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")


def format_id(application_id: int) -> str:
    return f"{application_id:0{ID_DIGITS}d}"


def next_id(tracker: Tracker) -> int:
    ids = [app.id for app in tracker.applications]
    ids += [row.id for row in tracker.inbox if row.id is not None]
    return max(ids, default=0) + 1


def safe_part(text: str) -> str:
    cleaned = WHITESPACE.sub(" ", UNSAFE_CHARACTERS.sub(" ", text)).strip()
    return cleaned[:MAX_NAME_PART].rstrip(" .") or "Unknown"


def folder_name(application_id: int, company: str, role: str, day: date) -> str:
    return f"{format_id(application_id)} {safe_part(company)} - {safe_part(role)} ({day})"


def move_folder(source: Path, data_root: Path, name: str) -> Path:
    folder = data_root / APPLICATIONS_DIR / name
    if folder.exists():
        shutil.rmtree(source)
        return folder
    folder.parent.mkdir(parents=True, exist_ok=True)
    source.rename(folder)
    return folder


def application_dir(data_root: Path, application: Application) -> Path | None:
    if not application.folder:
        return None
    folder = data_root / APPLICATIONS_DIR / application.folder
    return folder if folder.is_dir() else None


def add_timeline_event(folder: Path, day: date, event: str) -> None:
    timeline = folder / TIMELINE_FILE
    if not timeline.exists():
        timeline.write_text(TIMELINE_HEADING)
    with timeline.open("a") as file:
        file.write(f"- {day.isoformat()} {event}\n")


def event_line(day: date, event: str) -> re.Pattern[str]:
    return re.compile(rf"^- {day.isoformat()} {re.escape(event)}(:.*)?$")


def has_timeline_event(folder: Path, day: date, event: str) -> bool:
    timeline = folder / TIMELINE_FILE
    if not timeline.exists():
        return False
    pattern = event_line(day, event)
    return any(pattern.match(line) for line in timeline.read_text().splitlines())


def move_timeline_event(folder: Path, old: date, new: date, event: str) -> bool:
    timeline = folder / TIMELINE_FILE
    if not timeline.exists():
        return False
    pattern = event_line(old, event)
    lines = timeline.read_text().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if pattern.match(line.rstrip("\n")):
            lines[index] = line.replace(old.isoformat(), new.isoformat(), 1)
            timeline.write_text("".join(lines))
            return True
    return False


def remove_timeline_event(folder: Path, day: date, event: str) -> None:
    timeline = folder / TIMELINE_FILE
    if not timeline.exists():
        return
    pattern = event_line(day, event)
    kept = [
        line
        for line in timeline.read_text().splitlines(keepends=True)
        if not pattern.match(line.rstrip("\n"))
    ]
    timeline.write_text("".join(kept))
