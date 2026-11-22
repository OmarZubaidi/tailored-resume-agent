from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.config import (
    REPO_ROOT,
    ConfigError,
    Provider,
    config_path,
    load_config,
    resolve_data_root,
)


def test_example_config_loads_and_resolves_glob(config_data, write_config, data_root):
    write_config(config_data)

    config = load_config()

    assert config.data_root == data_root
    assert config.llm.provider is Provider.CLAUDE_CODE
    assert config.apply_on_my_behalf is False


def test_default_config_path_is_gitignored_repo_file(monkeypatch):
    monkeypatch.delenv("RESUME_AGENT_CONFIG", raising=False)

    path = config_path()

    assert path == REPO_ROOT / "config.yaml"
    assert "config.yaml" in (REPO_ROOT / ".gitignore").read_text().splitlines()


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Config not found"):
        load_config(tmp_path / "missing.yaml")


def test_non_mapping_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- a list\n")

    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        load_config(path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {
                "llm": {
                    "provider": "openai",
                },
            },
            "llm.provider",
        ),
        (
            {
                "llm": {
                    "provider": "codex",
                    "model": None,
                },
            },
            "llm.provider",
        ),
        (
            {
                "email": "not-an-email",
            },
            "not a valid email address",
        ),
        (
            {
                "links": {
                    "github": "github.com/x",
                },
            },
            "links.linkedin",
        ),
        (
            {
                "home_industry": "finance",
            },
            "has no entry in industry_keywords",
        ),
        (
            {
                "api_key": "sk-123",
            },
            "api_key",
        ),
        (
            {
                "email_scan_hours": 0,
            },
            "email_scan_hours",
        ),
    ],
)
def test_invalid_fields(config_data, write_config, change, message):
    write_config(
        {
            **config_data,
            **change,
        }
    )

    with pytest.raises(ConfigError, match=message):
        load_config()


@pytest.mark.parametrize(
    "key",
    [
        "data_root",
        "default_baseline",
        "apply_on_my_behalf",
        "email_scan_hours",
        "llm",
    ],
)
def test_every_key_is_required(config_data, write_config, key):
    write_config({name: value for name, value in config_data.items() if name != key})

    with pytest.raises(ConfigError, match=rf"{key}: missing; add it to config.yaml"):
        load_config()


def test_llm_model_key_is_required_but_may_be_null(config_data, write_config):
    write_config(
        {
            **config_data,
            "llm": {
                "provider": "ollama",
            },
        }
    )

    with pytest.raises(ConfigError, match="llm.model: missing"):
        load_config()


def test_glob_with_no_match(tmp_path):
    with pytest.raises(ValueError, match="found: none"):
        resolve_data_root(str(tmp_path / "ProtonDrive-*" / "Data"))


def test_glob_with_two_matches(tmp_path):
    (tmp_path / "ProtonDrive-a").mkdir()
    (tmp_path / "ProtonDrive-b").mkdir()

    with pytest.raises(ValueError, match="exactly one folder"):
        resolve_data_root(str(tmp_path / "ProtonDrive-*" / "Data"))


def test_path_without_glob_is_kept(tmp_path):
    assert resolve_data_root(str(tmp_path / "Data")) == tmp_path / "Data"


@pytest.mark.parametrize("pattern", [".", "Resume Agent Data"])
def test_relative_path_is_rejected(pattern):
    with pytest.raises(ValueError, match="must be an absolute path"):
        resolve_data_root(pattern)


def test_home_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve_data_root("~/Data") == Path(tmp_path, "Data")


def test_config_check_command_reports_errors(config_data, write_config):
    write_config(
        {
            **config_data,
            "email": "bad",
        }
    )

    result = CliRunner().invoke(app, ["config", "check"])

    assert result.exit_code == 1
    assert "not a valid email address" in result.output


def test_config_check_command_ok(config_data, write_config):
    write_config(config_data)

    result = CliRunner().invoke(app, ["config", "check"])

    assert result.exit_code == 0
    assert "Config OK" in result.output
