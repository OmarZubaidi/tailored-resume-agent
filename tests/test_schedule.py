import os
import plistlib
import subprocess

import pytest

from resume_agent.config import CONFIG_PATH_ENV, Config
from resume_agent.schedule import LABEL, ScheduleError, install_schedule


@pytest.fixture
def config(config_data) -> Config:
    return Config(**config_data)


@pytest.fixture
def program(tmp_path):
    path = tmp_path / "venv/bin/resume_agent"
    path.parent.mkdir(parents=True)
    path.write_text("")
    return path


class Launchctl:
    def __init__(self, bootstrap_code: int = 0) -> None:
        self.commands = []
        self.bootstrap_code = bootstrap_code

    def __call__(self, command: list[str], **options) -> subprocess.CompletedProcess:
        self.commands.append(command)
        code = self.bootstrap_code if command[1] == "bootstrap" else 3
        return subprocess.CompletedProcess(command, code, "", "Bootstrap failed: 5")


def test_plist_runs_the_scan_on_the_configured_interval(config, program, tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_PATH_ENV, "/somewhere/config.yaml")
    launchctl = Launchctl()

    path = install_schedule(config, home=tmp_path, program=program, run=launchctl)

    agent = plistlib.loads(path.read_bytes())
    assert path == tmp_path / f"Library/LaunchAgents/{LABEL}.plist"
    assert agent["ProgramArguments"] == [str(program), "gmail", "scan"]
    assert agent["StartInterval"] == 6 * 3600
    assert agent["RunAtLoad"] is True
    assert agent["EnvironmentVariables"][CONFIG_PATH_ENV] == "/somewhere/config.yaml"
    assert agent["StandardErrorPath"].endswith("Library/Logs/resume_agent/gmail-scan.log")


def test_reinstall_unloads_then_loads(config, program, tmp_path):
    launchctl = Launchctl()

    path = install_schedule(config, home=tmp_path, program=program, run=launchctl)

    domain = f"gui/{os.getuid()}"
    assert launchctl.commands == [
        ["launchctl", "bootout", f"{domain}/{LABEL}"],
        ["launchctl", "bootstrap", domain, str(path)],
    ]


def test_load_failure_is_reported(config, program, tmp_path):
    with pytest.raises(ScheduleError, match="Bootstrap failed"):
        install_schedule(config, home=tmp_path, program=program, run=Launchctl(bootstrap_code=5))


def test_missing_cli_is_reported(config, tmp_path):
    with pytest.raises(ScheduleError, match="pip install -e"):
        install_schedule(config, home=tmp_path, program=tmp_path / "missing", run=Launchctl())
