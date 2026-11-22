import hashlib
import stat
from datetime import date
from pathlib import Path

from resume_agent.config import Config

GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)
DRAFTS_DIR = "drafts"
NOTES_FILE = "notes.md"
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class GuardError(Exception):
    pass


def require_apply_allowed(config: Config) -> None:
    if not config.apply_on_my_behalf:
        raise GuardError(
            "apply_on_my_behalf is false. Only you can enable it, by editing config.yaml by hand."
        )


def excel_lock_file(workbook: Path) -> Path:
    return workbook.with_name(f"~${workbook.name}")


def ensure_excel_closed(workbook: Path) -> None:
    if excel_lock_file(workbook).exists():
        raise GuardError(
            f"{workbook.name} is open in Excel. Close it first; writing while it is open makes "
            "Proton Drive create conflicted copies."
        )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_locked(path: Path) -> bool:
    return path.exists() and not path.stat().st_mode & WRITE_BITS


def require_files(folder: Path, names: list[str]) -> None:
    missing = [name for name in names if not (folder / name).is_file()]
    if missing:
        raise GuardError(f"Cannot lock, missing in {folder.name}: {', '.join(missing)}")


def lock_applied_files(folder: Path, names: list[str], today: date | None = None) -> None:
    today = today or date.today()
    require_files(folder, names)

    lines = []
    for name in names:
        path = folder / name
        if is_locked(path):
            continue
        path.chmod(path.stat().st_mode & ~WRITE_BITS)
        lines.append(f"- {today.isoformat()} locked `{name}` sha256 `{sha256(path)}`\n")

    with (folder / NOTES_FILE).open("a") as notes:
        notes.writelines(lines)


def writable_target(folder: Path, name: str) -> Path:
    target = folder / name
    if not is_locked(target):
        return target
    drafts = folder / DRAFTS_DIR
    drafts.mkdir(exist_ok=True)
    return drafts / name
