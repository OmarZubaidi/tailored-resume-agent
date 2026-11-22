import json
import re
from string import Template

from resume_agent.config import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"
JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class PromptError(Exception):
    pass


def render_prompt(name: str, **values: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    try:
        return Template(path.read_text()).substitute(values)
    except FileNotFoundError as error:
        raise PromptError(f"Prompt not found: {path}") from error
    except KeyError as error:
        raise PromptError(f"Prompt {name} needs a value for {error}") from error


def parse_json_reply(reply: str) -> dict:
    fenced = JSON_BLOCK.search(reply)
    text = fenced.group(1) if fenced else reply[reply.find("{") : reply.rfind("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise PromptError(f"Expected JSON from the model, got: {reply[:200]}") from error
    if not isinstance(data, dict):
        raise PromptError("Expected a JSON object from the model")
    return data
