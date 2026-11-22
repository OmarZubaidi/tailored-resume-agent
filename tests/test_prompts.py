import pytest

from resume_agent.prompts import PROMPTS_DIR, PromptError, parse_json_reply, render_prompt

TAILOR_VALUES = {
    "mode": "upward",
    "home_industry": "healthcare",
    "industry_keywords": "FHIR, EHR",
    "listing": "LISTING TEXT",
    "baseline": "BASELINE",
    "bullet_bank": "B1: Built things.",
    "ledger": "TypeScript: 24 months",
    "tailoring_rules": "None",
}


def test_tailor_prompt_fills_every_value():
    prompt = render_prompt("tailor-resume", **TAILOR_VALUES)

    assert "LISTING TEXT" in prompt
    assert "B1: Built things." in prompt
    assert "$" not in prompt


def test_missing_value_names_it():
    with pytest.raises(PromptError, match="needs a value for 'listing'"):
        render_prompt("triage-fit")


def test_unknown_prompt():
    with pytest.raises(PromptError, match="Prompt not found"):
        render_prompt("nope")


@pytest.mark.parametrize("name", ["tailor-resume", "cover-letter", "triage-fit"])
def test_prompts_have_no_dashes(name):
    text = (PROMPTS_DIR / f"{name}.md").read_text()

    assert "—" not in text
    assert "–" not in text


@pytest.mark.parametrize(
    "reply",
    [
        '{"years_required": 3}',
        'Here you go:\n```json\n{"years_required": 3}\n```',
        'Sure. {"years_required": 3} Done.',
    ],
)
def test_parse_json_reply(reply):
    assert parse_json_reply(reply) == {"years_required": 3}


def test_parse_json_reply_rejects_prose():
    with pytest.raises(PromptError, match="Expected JSON"):
        parse_json_reply("I can't help with that.")
