import io
import json
import subprocess
from pathlib import Path

import pytest

from resume_agent import llm
from resume_agent.config import Config, Provider
from resume_agent.llm import (
    DESKTOP_CLAUDE,
    PROVIDERS,
    VSCODE_CLAUDE,
    LlmError,
    find_claude,
    run_prompt,
)


def make_binary(home: Path, pattern: str, version: str) -> Path:
    path = home / pattern.replace("*", version, 1).replace("*", "abc123")
    path.parent.mkdir(parents=True)
    path.write_text("")
    return path


@pytest.fixture
def no_claude_on_path(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda _: None)


def config_with(config_data, provider: Provider, model: str | None = None) -> Config:
    return Config(
        **{
            **config_data,
            "llm": {
                "provider": provider.value,
                "model": model,
            },
        }
    )


def test_every_provider_is_wired():
    assert set(PROVIDERS) == set(Provider)


def test_claude_on_path_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(llm.shutil, "which", lambda _: "/usr/local/bin/claude")
    make_binary(tmp_path, DESKTOP_CLAUDE, "2.1.330")

    assert find_claude(tmp_path) == Path("/usr/local/bin/claude")


def test_newest_desktop_bundle_before_vscode(no_claude_on_path, tmp_path):
    make_binary(tmp_path, DESKTOP_CLAUDE, "2.1.9")
    newest = make_binary(tmp_path, DESKTOP_CLAUDE.replace("*/*", "2.1.330/*", 1), "x")
    make_binary(tmp_path, VSCODE_CLAUDE, "9.9.9-darwin-arm64")

    assert find_claude(tmp_path) == newest


def test_vscode_bundle_when_no_desktop(no_claude_on_path, tmp_path):
    vscode = make_binary(tmp_path, VSCODE_CLAUDE, "2.1.330-darwin-arm64")

    assert find_claude(tmp_path) == vscode


def test_no_claude_anywhere(no_claude_on_path, tmp_path):
    with pytest.raises(LlmError, match="Claude Code not found"):
        find_claude(tmp_path)


def test_cli_providers_drop_pay_per_use_keys(monkeypatch, config_data):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-123")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-456")
    monkeypatch.setattr(llm, "find_claude", lambda: Path("/bin/claude"))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=" tailored \n", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    output = run_prompt(config_with(config_data, Provider.CLAUDE_CODE, "sonnet"), "Hi")

    command, kwargs = calls[0]
    assert output == "tailored"
    assert command == [
        "/bin/claude",
        "-p",
        "--output-format",
        "text",
        "--tools",
        "",
        "--strict-mcp-config",
        "--model",
        "sonnet",
    ]
    assert kwargs["input"] == "Hi"
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert "OPENAI_API_KEY" not in kwargs["env"]


def test_cli_failure_is_an_llm_error(monkeypatch, config_data):
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 1, stdout="", stderr="limit"),
    )

    with pytest.raises(LlmError, match="codex failed: limit"):
        run_prompt(config_with(config_data, Provider.CODEX), "Hi")


def test_ollama_requires_model(config_data):
    with pytest.raises(LlmError, match="Set llm.model"):
        run_prompt(config_with(config_data, Provider.OLLAMA), "Hi")


def test_ollama_posts_to_localhost(monkeypatch, config_data):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return io.BytesIO(json.dumps({"response": " done "}).encode())

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)

    output = run_prompt(config_with(config_data, Provider.OLLAMA, "llama3"), "Hi")

    payload = json.loads(requests[0].data)
    assert output == "done"
    assert requests[0].full_url == "http://localhost:11434/api/generate"
    assert payload["model"] == "llama3"
    assert payload["options"]["num_ctx"] >= 16_384


@pytest.mark.parametrize("body", [b"not json", b'{"unexpected": true}'])
def test_malformed_local_reply_is_an_llm_error(monkeypatch, config_data, body):
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(body))

    with pytest.raises(LlmError):
        run_prompt(config_with(config_data, Provider.LMSTUDIO), "Hi")


def test_unreachable_local_server(monkeypatch, config_data):
    def refuse(request, timeout):
        raise llm.urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", refuse)

    with pytest.raises(LlmError, match="is the local model server running"):
        run_prompt(config_with(config_data, Provider.LMSTUDIO), "Hi")
