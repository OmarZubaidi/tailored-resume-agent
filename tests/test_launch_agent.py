import os
import plistlib
import subprocess

import pytest

from resume_agent.config import CONFIG_PATH_ENV, Config
from resume_agent.launch_agent import LABEL, LaunchAgentError, install_sync_agent


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
    def __init__(self, *bootstrap_codes: int) -> None:
        self.commands = []
        self.bootstrap_codes = list(bootstrap_codes or [0])

    def __call__(self, command: list[str], **options) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command[1] != "bootstrap":
            return subprocess.CompletedProcess(command, 3, "", "")
        code = (
            self.bootstrap_codes.pop(0)
            if len(self.bootstrap_codes) > 1
            else self.bootstrap_codes[0]
        )
        return subprocess.CompletedProcess(command, code, "", f"Bootstrap failed: {code}")


def no_wait(seconds: float) -> None:
    pass


def test_agent_runs_sync_when_the_data_folder_changes(config, program, tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_PATH_ENV, "/somewhere/config.yaml")

    path = install_sync_agent(config, home=tmp_path, program=program, run=Launchctl())

    agent = plistlib.loads(path.read_bytes())
    assert path == tmp_path / f"Library/LaunchAgents/{LABEL}.plist"
    assert agent["ProgramArguments"] == [str(program), "sync"]
    assert agent["WatchPaths"] == [str(config.data_root)]
    assert agent["RunAtLoad"] is True
    assert agent["EnvironmentVariables"][CONFIG_PATH_ENV] == "/somewhere/config.yaml"
    assert agent["StandardErrorPath"].endswith("Library/Logs/resume_agent/sync.log")


def test_reinstall_unloads_then_loads(config, program, tmp_path):
    launchctl = Launchctl()

    path = install_sync_agent(config, home=tmp_path, program=program, run=launchctl)

    domain = f"gui/{os.getuid()}"
    assert launchctl.commands == [
        ["launchctl", "bootout", f"{domain}/{LABEL}"],
        ["launchctl", "bootstrap", domain, str(path)],
    ]


def test_load_retries_while_the_old_job_unloads(config, program, tmp_path):
    launchctl = Launchctl(5, 5, 0)

    install_sync_agent(config, home=tmp_path, program=program, run=launchctl, sleep=no_wait)

    assert [command[1] for command in launchctl.commands] == [
        "bootout",
        "bootstrap",
        "bootstrap",
        "bootstrap",
    ]


def test_load_failure_is_reported(config, program, tmp_path):
    with pytest.raises(LaunchAgentError, match="Bootstrap failed: 5"):
        install_sync_agent(config, home=tmp_path, program=program, run=Launchctl(5), sleep=no_wait)


def test_relative_config_path_is_made_absolute(config, program, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(CONFIG_PATH_ENV, "config.yaml")

    path = install_sync_agent(config, home=tmp_path, program=program, run=Launchctl())

    environment = plistlib.loads(path.read_bytes())["EnvironmentVariables"]
    assert environment[CONFIG_PATH_ENV] == str((tmp_path / "config.yaml").resolve())


def test_missing_cli_is_reported(config, tmp_path):
    with pytest.raises(LaunchAgentError, match="pip install -e"):
        install_sync_agent(config, home=tmp_path, program=tmp_path / "missing", run=Launchctl())
