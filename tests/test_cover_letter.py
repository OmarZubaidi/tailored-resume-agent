from datetime import date

import pytest

from resume_agent.cover_letter import (
    MAX_LETTER_WORDS,
    style_problems,
    write_cover_letter,
    years_in_words,
)
from resume_agent.documents import DocumentError
from resume_agent.ledger import load_ledger

TEMPLATE = """---
title: Cover Letter
---

Dear [Hiring Manager's Name],

Over the past three years, I've built things at [Company Name].

Best,
"""
LETTER = """Dear Hiring Team,

Over the past five years at Acme, I've built things for Globex.

Best,"""


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "skills-ledger.yaml"
    path.write_text("roles:\n  Acme:\n    from: 05/2021\n    to: present\n")
    return load_ledger(path, date(2026, 11, 21))


def scripted(*replies: str):
    queue = list(replies)
    prompts: list[str] = []

    def run(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0)

    return run, prompts


def generate(run, ledger):
    return write_cover_letter(run, "LISTING", "Engineer", "RESUME", TEMPLATE, ledger)


@pytest.mark.parametrize(
    ("months", "words"),
    [
        (11, "zero"),
        (66, "five"),
        (12 * 25, "25"),
    ],
)
def test_years_in_words(months, words):
    assert years_in_words(months) == words


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("I am genuinely glad.", "uses the banned phrase 'genuinely'"),
        ("Honestly, I love APIs.", "uses the banned phrase 'Honestly'"),
        ("I have a proven track record.", "uses the banned phrase 'proven track record'"),
        ("A fast-paced team.", "uses the banned phrase 'fast-paced'"),
        ("Let's make great things happen.", "uses the banned phrase 'great things happen'"),
        ("It's not just code, it's craft.", "uses contrast framing"),
        ("It's not about speed, it's about care.", "uses contrast framing"),
        ("I bring not only skill, but grit.", "uses contrast framing"),
        ("Built it fast — and well.", "uses an en or em dash"),
        ("On your stack: I know it.", "uses a colon: 'stack:'"),
        ("I like [Company Name].", "leaves the placeholder [Company Name]"),
        ("i built the fax api.", "starts a sentence in lowercase: 'i'"),
        ("I built it. then I tested it.", "starts a sentence in lowercase: 'then'"),
        ("Dear team,\n\nhappy to talk.", "starts a sentence in lowercase: 'happy'"),
        ("Since then i have shipped it.", "writes 'I' in lowercase"),
        ("Glad to help, i'm free Monday.", "writes 'I' in lowercase"),
        ("I dont mind on-call.", "drops the apostrophe in 'dont'"),
        ("Im happy to talk.", "drops the apostrophe in 'Im'"),
    ],
)
def test_style_problems(text, problem):
    assert any(problem in found for found in style_problems(text)), style_problems(text)


def test_plain_writing_has_no_style_problems():
    assert style_problems("I'm not sure, but I built a fax (yes, that fax!) REST API.") == []


def test_abbreviations_and_mixed_case_names_pass_the_casing_check():
    text = "I used tools, e.g. pytest, i.e. the usual. It ships at 9:30 on iOS.\n\nBest,\nJane"

    assert style_problems(text) == []


def test_generated_letter(ledger):
    run, prompts = scripted(LETTER)

    generated = generate(run, ledger)

    assert len(prompts) == 1
    assert "five" in prompts[0]
    assert "Treat the template as a suggestion" in prompts[0]
    assert '"genuinely"' in prompts[0]
    assert "Dear [Hiring Manager's Name]," in prompts[0]
    assert "title: Cover Letter" not in prompts[0]
    assert generated.letter.closing == "Best,"
    assert generated.markdown.startswith("---\ntitle: Cover Letter\n---\n\nDear Hiring Team,")
    assert generated.flags == [f"Years: {LETTER.splitlines()[2]}"]


def test_llm_verbiage_gets_one_revision(ledger):
    draft = "Dear team,\n\nI am genuinely thrilled — truly.\n\nBest,"
    run, prompts = scripted(draft, LETTER)

    generated = generate(run, ledger)

    assert "Your draft below breaks these rules:" in prompts[1]
    assert "- uses the banned phrase 'genuinely'" in prompts[1]
    assert "- uses an en or em dash" in prompts[1]
    assert generated.letter.paragraphs[0] == "Dear Hiring Team,"


def test_long_draft_gets_one_revision(ledger):
    run, prompts = scripted("Dear team,\n\n" + "word " * 330 + "\n\nBest,", LETTER)

    generate(run, ledger)

    assert f"under {MAX_LETTER_WORDS} words" in prompts[0]
    assert f"- is 333 words; the limit is {MAX_LETTER_WORDS}" in prompts[1]


def test_verbiage_that_survives_revision_fails(ledger):
    stubborn = "Dear team,\n\nIt's not just code, it's craft.\n\nBest,"
    run, _ = scripted(stubborn, stubborn)

    with pytest.raises(DocumentError, match="Cover letter still uses contrast framing"):
        generate(run, ledger)


def test_leftover_placeholder_fails_after_revision(ledger):
    placeholder = "Dear team,\n\nI like [Company Name].\n\nBest,"
    run, _ = scripted(placeholder, placeholder)

    with pytest.raises(DocumentError, match=r"leaves the placeholder \[Company Name\]"):
        generate(run, ledger)
