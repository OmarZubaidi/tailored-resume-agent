import os
import plistlib
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from resume_agent.config import CONFIG_PATH_ENV, Config

LABEL = "com.resume-agent.sync"
PASSED_ENVIRONMENT = ("PATH", CONFIG_PATH_ENV)
THROTTLE_SECONDS = 10
STILL_UNLOADING = 5
BOOTSTRAP_ATTEMPTS = 5
BOOTSTRAP_RETRY_SECONDS = 1.0


class LaunchAgentError(Exception):
    pass


def agent_path(home: Path) -> Path:
    return home / "Library/LaunchAgents" / f"{LABEL}.plist"


def log_path(home: Path) -> Path:
    return home / "Library/Logs/resume_agent/sync.log"


def agent_plist(program: Path, data_root: Path, log: Path, environment: dict[str, str]) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(program), "sync"],
        "WatchPaths": [str(data_root)],
        "RunAtLoad": True,
        "ThrottleInterval": THROTTLE_SECONDS,
        "EnvironmentVariables": environment,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def install_sync_agent(
    config: Config,
    home: Path | None = None,
    program: Path | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    home = home or Path.home()
    program = program or Path(sys.executable).parent / "resume_agent"
    if not program.is_file():
        raise LaunchAgentError(
            f"{program} not found. Install the CLI with `.venv/bin/pip install -e .`"
        )
    log = log_path(home)
    log.parent.mkdir(parents=True, exist_ok=True)
    environment = {key: os.environ[key] for key in PASSED_ENVIRONMENT if key in os.environ}
    if CONFIG_PATH_ENV in environment:
        environment[CONFIG_PATH_ENV] = str(
            Path(environment[CONFIG_PATH_ENV]).expanduser().resolve()
        )
    path = agent_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(agent_plist(program, config.data_root, log, environment)))

    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True, text=True)
    for attempt in range(BOOTSTRAP_ATTEMPTS):
        loaded = run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
        if loaded.returncode != STILL_UNLOADING or attempt == BOOTSTRAP_ATTEMPTS - 1:
            break
        sleep(BOOTSTRAP_RETRY_SECONDS)
    if loaded.returncode != 0:
        raise LaunchAgentError(f"launchctl could not load {path}: {loaded.stderr.strip()}")
    return path
