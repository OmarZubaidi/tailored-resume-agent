import subprocess
from collections.abc import Callable

TITLE = "Resume agent"
SYNC_STOPPED = "Sync stopped with an error. See sync.log."
SCRIPT = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
TIMEOUT_SECONDS = 10


def notify(message: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    try:
        run(
            ["osascript", "-e", SCRIPT, TITLE, message],
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def problems_message(failed: int, flagged: int) -> str | None:
    parts = [f"{failed} failed"] if failed else []
    if flagged:
        parts.append(f"{flagged} waiting for review")
    return f"{', '.join(parts)}. See sync.log." if parts else None
