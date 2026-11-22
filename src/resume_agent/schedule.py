import os
import plistlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from resume_agent.config import CONFIG_PATH_ENV, Config

LABEL = "com.resume-agent.gmail-scan"
SECONDS_PER_HOUR = 3_600
PASSED_ENVIRONMENT = ("PATH", CONFIG_PATH_ENV)


class ScheduleError(Exception):
    pass


def agent_path(home: Path) -> Path:
    return home / "Library/LaunchAgents" / f"{LABEL}.plist"


def log_path(home: Path) -> Path:
    return home / "Library/Logs/resume_agent/gmail-scan.log"


def agent_plist(program: Path, hours: int, log: Path, environment: dict[str, str]) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(program), "gmail", "scan"],
        "StartInterval": hours * SECONDS_PER_HOUR,
        "RunAtLoad": True,
        "EnvironmentVariables": environment,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def install_schedule(
    config: Config,
    home: Path | None = None,
    program: Path | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    home = home or Path.home()
    program = program or Path(sys.executable).parent / "resume_agent"
    if not program.is_file():
        raise ScheduleError(
            f"{program} not found. Install the CLI with `.venv/bin/pip install -e .`"
        )
    log = log_path(home)
    log.parent.mkdir(parents=True, exist_ok=True)
    environment = {key: os.environ[key] for key in PASSED_ENVIRONMENT if key in os.environ}
    path = agent_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        plistlib.dumps(agent_plist(program, config.email_scan_hours, log, environment))
    )

    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True, text=True)
    loaded = run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if loaded.returncode != 0:
        raise ScheduleError(f"launchctl could not load {path}: {loaded.stderr.strip()}")
    return path
