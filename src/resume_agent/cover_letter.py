import re
from collections.abc import Callable
from dataclasses import dataclass, field

from resume_agent.documents import (
    FRONT_MATTER_DELIMITER,
    CoverLetter,
    DocumentError,
    open_placeholders,
    parse_cover_letter,
    split_front_matter,
)
from resume_agent.ledger import Ledger, whole_years
from resume_agent.prompts import render_prompt
from resume_agent.validation import word_count

NUMBER_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty"
).split()
LONG_DASH = re.compile(r"[–—]")
SENTENCE_COLON = re.compile(r"\w+:(?=\s)")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
STARTS_WITH_I = re.compile(r"I\b")
MAX_I_RUN = 3
YEARS_MENTION = re.compile(r"\b\w+\+? years?\b", re.IGNORECASE)
NO_VOICE_NOTES = "None yet. Write in a plain, professional register."
NO_STORY_NOTES = "None yet. Tell stories from the resume's facts alone."
MAX_LETTER_WORDS = 320
BANNED_WORDS = (
    "honestly",
    "genuinely",
    "truly",
    "delve",
    "testament",
    "tapestry",
    "thrilled",
    "passionate",
    "seamless",
    "seamlessly",
    "excited",
    "eager",
    "writing to express",
    "proven track record",
    "results-driven",
    "dynamic",
    "fast-paced",
    "esteemed",
    "strong foundation",
    "great things happen",
    "leverage",
    "synergy",
    "great fit",
    "circle back",
    "touch base",
    "bandwidth",
    "move the needle",
    "low-hanging fruit",
    "deep dive",
    "value-add",
    "value add",
    "best-in-class",
    "game-changer",
    "game changer",
    "wheelhouse",
    "outside the box",
    "hit the ground running",
    "spearhead",
    "spearheaded",
    "utilize",
    "cutting-edge",
    "world-class",
    "empower",
    "holistic",
    "paradigm",
    "matters",
)
BANNED_WORD = re.compile(
    rf"\b({'|'.join(re.escape(word) for word in BANNED_WORDS)})\b", re.IGNORECASE
)
ABBREVIATION = re.compile(r"\b(?:e\.g|i\.e|etc|vs)\.", re.IGNORECASE)
LOWERCASE_START = re.compile(r"(?:^|[.!?]\s+|\n\s*)([a-z][a-z0-9-]*)\b", re.MULTILINE)
LOWERCASE_I = re.compile(r"(?<![\w.])i(?=[\s,;:!?']|$)")
CONTRACTIONS_WITHOUT_APOSTROPHE = (
    "dont cant wont isnt arent doesnt didnt wasnt werent hasnt havent couldnt shouldnt wouldnt "
    "im ive youre theyre thats whats"
).split()
MISSING_APOSTROPHE = re.compile(
    rf"\b({'|'.join(CONTRACTIONS_WITHOUT_APOSTROPHE)})\b", re.IGNORECASE
)
CONTRAST_FRAMING = re.compile(
    r"\bnot (?:just|only|merely|simply)\b[^.!?]*?[,;]\s*(?:but|it'?s|it is|they'?re|we'?re)\b"
    r"|\bit'?s not (?:about )?[^.!?,]+,\s*it'?s\b",
    re.IGNORECASE,
)


@dataclass
class GeneratedLetter:
    letter: CoverLetter
    markdown: str
    flags: list[str] = field(default_factory=list)


def years_in_words(months: int) -> str:
    years = whole_years(months)
    return NUMBER_WORDS[years] if years < len(NUMBER_WORDS) else str(years)


def template_body(template: str) -> str:
    _, lines = split_front_matter(template)
    return "\n".join(lines).strip()


def letter_markdown(letter: CoverLetter) -> str:
    front = f"{FRONT_MATTER_DELIMITER}\ntitle: {letter.title}\n{FRONT_MATTER_DELIMITER}"
    body = "\n\n".join([*letter.paragraphs, letter.closing])
    return f"{front}\n\n{body}\n"


def casing_problems(text: str) -> list[str]:
    plain = ABBREVIATION.sub("", text)
    problems = [
        f"starts a sentence in lowercase: {word!r}" for word in LOWERCASE_START.findall(plain)
    ]
    if LOWERCASE_I.search(plain):
        problems.append("writes 'I' in lowercase")
    problems += [f"drops the apostrophe in {word!r}" for word in MISSING_APOSTROPHE.findall(plain)]
    return problems


def starts_with_i_run(text: str) -> bool:
    run = 0
    for sentence in SENTENCE_BREAK.split(text):
        run = run + 1 if STARTS_WITH_I.match(sentence) else 0
        if run >= MAX_I_RUN:
            return True
    return False


def style_problems(text: str) -> list[str]:
    problems = [f"uses the banned phrase {word!r}" for word in BANNED_WORD.findall(text)]
    problems += [f"uses contrast framing: {match!r}" for match in CONTRAST_FRAMING.findall(text)]
    if LONG_DASH.search(text):
        problems.append("uses an en or em dash")
    problems += [f"uses a colon: {match!r}" for match in SENTENCE_COLON.findall(text)]
    if starts_with_i_run(text):
        problems.append(f"starts {MAX_I_RUN} sentences in a row with 'I'")
    problems += casing_problems(text)
    problems += [f"leaves the placeholder {item}" for item in open_placeholders(text.splitlines())]
    return problems


def revision_request(prompt: str, draft: str, issues: list[str]) -> str:
    listed = "\n".join(f"- {issue}" for issue in issues)
    return (
        f"{prompt}\n\nYour draft below breaks these rules:\n{listed}\n\n"
        f"Rewrite it to fix every one, keeping every other rule above.\n\n{draft}"
    )


def write_cover_letter(
    run: Callable[[str], str],
    listing: str,
    job_title: str,
    resume_markdown: str,
    template: str,
    ledger: Ledger,
    voice: str = "",
    stories: str = "",
) -> GeneratedLetter:
    years = years_in_words(ledger.experience_months())
    body = template_body(template)
    max_words = MAX_LETTER_WORDS
    prompt = render_prompt(
        "cover-letter",
        job_title=job_title,
        years=years,
        listing=listing,
        resume=resume_markdown,
        template=body,
        voice=voice.strip() or NO_VOICE_NOTES,
        stories=stories.strip() or NO_STORY_NOTES,
        max_words=str(max_words),
        banned_words=", ".join(f'"{word}"' for word in BANNED_WORDS),
    )
    reply = run(prompt).strip()
    issues = style_problems(reply)
    if word_count(reply) > max_words:
        issues.append(f"is {word_count(reply)} words; the limit is {max_words}")
    if issues:
        reply = run(revision_request(prompt, reply, issues)).strip()
        remaining = style_problems(reply)
        if remaining:
            raise DocumentError(f"Cover letter still {'; '.join(remaining)}")

    title = parse_cover_letter(template).title
    letter = parse_cover_letter(
        f"{FRONT_MATTER_DELIMITER}\ntitle: {title}\n{FRONT_MATTER_DELIMITER}\n{reply}"
    )

    flags = [
        f"Years: {paragraph[:120]}"
        for paragraph in letter.paragraphs
        if YEARS_MENTION.search(paragraph)
    ]
    return GeneratedLetter(letter=letter, markdown=letter_markdown(letter), flags=flags)
