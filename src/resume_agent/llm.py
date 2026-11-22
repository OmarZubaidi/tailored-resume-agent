import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from resume_agent.config import Config, Provider

TIMEOUT_SECONDS = 600
PAY_PER_USE_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY")
DESKTOP_CLAUDE = (
    "Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude"
)
VSCODE_CLAUDE = ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"
OLLAMA_URL = "http://localhost:11434/api/generate"
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
NO_MCP = ("--strict-mcp-config",)
OLLAMA_CONTEXT_TOKENS = 16_384


class LlmError(Exception):
    pass


def version_key(path: Path) -> tuple[int, ...]:
    match = VERSION.search(str(path))
    return tuple(int(part) for part in match.groups()) if match else (0,)


def newest(home: Path, pattern: str) -> Path | None:
    matches = sorted(home.glob(pattern), key=version_key)
    return matches[-1] if matches else None


def find_claude(home: Path | None = None) -> Path:
    home = home or Path.home()
    on_path = shutil.which("claude")
    if on_path:
        return Path(on_path)
    found = newest(home, DESKTOP_CLAUDE) or newest(home, VSCODE_CLAUDE)
    if not found:
        raise LlmError(
            "Claude Code not found. Install Claude Desktop or the Claude Code VS Code extension, "
            "or put `claude` on your PATH."
        )
    return found


def subscription_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in PAY_PER_USE_KEYS}


def run_cli(command: list[str], prompt: str) -> str:
    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=subscription_env(),
        )
    except FileNotFoundError as error:
        raise LlmError(f"{command[0]} not found") from error
    except subprocess.TimeoutExpired as error:
        raise LlmError(f"{Path(command[0]).name} timed out after {TIMEOUT_SECONDS}s") from error
    if result.returncode != 0:
        raise LlmError(f"{Path(command[0]).name} failed: {result.stderr.strip() or result.stdout}")
    return result.stdout.strip()


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except json.JSONDecodeError as error:
        raise LlmError(f"{url} did not return JSON: {error}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        message = f"Could not reach {url}; is the local model server running? {error}"
        raise LlmError(message) from error


def claude_code(prompt: str, model: str | None) -> str:
    # Listings are untrusted text, so the model gets no tools to act on what they say.
    command = [str(find_claude()), "-p", "--output-format", "text", "--tools", "", *NO_MCP]
    return run_cli(command + (["--model", model] if model else []), prompt)


def reply_field(reply: dict, *path: str | int) -> str:
    try:
        for key in path:
            reply = reply[key]
        return str(reply).strip()
    except (KeyError, IndexError, TypeError) as error:
        raise LlmError(f"Unexpected reply from the local model server: {reply}") from error


def ollama(prompt: str, model: str | None) -> str:
    if not model:
        raise LlmError("Set llm.model in config.yaml to an Ollama model name")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": OLLAMA_CONTEXT_TOKENS},
    }
    return reply_field(post_json(OLLAMA_URL, payload), "response")


def lmstudio(prompt: str, model: str | None) -> str:
    payload = {
        "model": model or "local-model",
        "messages": [
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }
    return reply_field(post_json(LMSTUDIO_URL, payload), "choices", 0, "message", "content")


PROVIDERS: dict[Provider, Callable[[str, str | None], str]] = {
    Provider.CLAUDE_CODE: claude_code,
    Provider.OLLAMA: ollama,
    Provider.LMSTUDIO: lmstudio,
}


def run_prompt(config: Config, prompt: str) -> str:
    return PROVIDERS[config.llm.provider](prompt, config.llm.model)
