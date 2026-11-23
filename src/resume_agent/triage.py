import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from resume_agent.config import Config
from resume_agent.job_listing import Listing
from resume_agent.ledger import Ledger, LedgerError, load_ledger, whole_years
from resume_agent.llm import LlmError
from resume_agent.prompts import PromptError, parse_json_reply, render_prompt, text_value

TRIAGE_MD = "triage.md"
YEARS_FILE = "years.json"
STALE_AFTER = timedelta(hours=72)
JOB_BOARDS = (
    "linkedin.com",
    "indeed.com",
    "dice.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "monster.com",
    "simplyhired.com",
    "wellfound.com",
    "builtin.com",
)
PATH_ATS_HOSTS = (
    "greenhouse.io",
    "ashbyhq.com",
    "lever.co",
    "workable.com",
    "smartrecruiters.com",
)
SUBDOMAIN_ATS_HOST = ".myworkdayjobs.com"
POSTED_AGO = re.compile(r"\bposted\s+(\d+)\+?\s+(hour|day|week|month)s?\s+ago", re.IGNORECASE)
POSTED_RECENT = re.compile(r"\bposted\s+(today|yesterday|just now)", re.IGNORECASE)
POSTED_ON = re.compile(r"\b(?i:posted)(?:\s+on)?:?\s+([A-Z][a-z]+ \d{1,2},? \d{4})")
NEGATION = re.compile(r"\b(no|not|without)\b", re.IGNORECASE)
AGO_UNITS = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}
CLEARANCE = re.compile(
    r"\b(security clearance|clearance required|TS/SCI|top secret)\b", re.IGNORECASE
)
CITIZENSHIP = re.compile(
    r"\b(U\.?S\.? citizen(ship)? (is )?required|must be a U\.?S\.? citizen)", re.IGNORECASE
)
WORK_AUTHORIZATION = re.compile(
    r"\b(sponsor(ship)?|authorized to work|work authorization|visa)\b", re.IGNORECASE
)
DEGREE = re.compile(
    r"\b(bachelor'?s|master'?s|B\.?S\.?|M\.?S\.?|B\.?A\.?|degree)\b[^.\n]*"
    r"\b(computer science|engineering|related field|technical field)\b",
    re.IGNORECASE,
)
PREFERRED = re.compile(r"\b(preferred|nice to have|bonus|plus)\b", re.IGNORECASE)
REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)
IN_PERSON = re.compile(r"\b(hybrid|on-?site|in[- ]office|in the office)\b", re.IGNORECASE)
SENTENCE_BREAK = re.compile(r"(?<=[a-z0-9)][.!?])\s+(?=[A-Z])|\n+")


@dataclass
class Triage:
    title: str
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fit_checked: bool = False
    company: str = ""
    role: str = ""
    years_max: int | None = None

    @property
    def flagged(self) -> bool:
        return bool(self.flags)

    def markdown(self) -> str:
        lines = [
            f"# Triage: {self.title}",
            "",
            f"Company: {self.company or 'unknown'}",
            f"Role: {self.role or 'unknown'}",
            "",
            f"Result: **{'FLAGGED' if self.flagged else 'CLEAR'}**",
            "",
            "## Flags",
            *(f"- {flag}" for flag in self.flags or ["None"]),
            "",
            "## Notes",
            *(f"- {note}" for note in self.notes or ["None"]),
            "",
        ]
        if not self.fit_checked:
            lines += [
                "## Pending",
                "- Years of experience against the skills ledger.",
                "",
            ]
        return "\n".join(lines)


@dataclass
class Requirements:
    years_required: int | None
    other_requirements: list[str]
    company: str = ""
    role: str = ""
    years_max: int | None = None


def extract_requirements(run: Callable[[str], str], listing_text: str) -> Requirements:
    data = parse_json_reply(run(render_prompt("triage-fit", listing=listing_text)))
    return Requirements(
        years_required=whole_number(data.get("years_required")),
        other_requirements=string_list(data.get("other_requirements")),
        company=text_value(data.get("company")),
        role=text_value(data.get("role")),
        years_max=whole_number(data.get("years_max")),
    )


def save_years(folder: Path, triage: Triage) -> None:
    path = folder / YEARS_FILE
    if triage.fit_checked:
        path.write_text(json.dumps({"years_max": triage.years_max}))
    else:
        path.unlink(missing_ok=True)


def listing_years_max(folder: Path, listing_text: str, run: Callable[[str], str]) -> int | None:
    try:
        saved = json.loads((folder / YEARS_FILE).read_text())
    except (FileNotFoundError, ValueError):
        saved = None
    if isinstance(saved, dict):
        return whole_number(saved.get("years_max"))
    return extract_requirements(run, listing_text).years_max


def whole_number(value: object) -> int | None:
    valid = isinstance(value, int | float) and not isinstance(value, bool)
    return int(value) if valid else None


def string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def apply_fit(triage: Triage, requirements: Requirements, ledger: Ledger) -> Triage:
    experience = whole_years(ledger.experience_months())
    if requirements.years_required and requirements.years_required > experience:
        triage.flags.append(
            f"Years: the listing asks for {requirements.years_required}, "
            f"the ledger shows {experience}."
        )
    triage.notes.extend(f"Requirement: {item}" for item in requirements.other_requirements)
    triage.years_max = requirements.years_max
    triage.fit_checked = True
    return triage


def add_fit(
    triage: Triage, listing_text: str, ledger_path: Path, run: Callable[[str], str]
) -> Triage:
    try:
        requirements = extract_requirements(run, listing_text)
        triage.company = requirements.company or triage.company
        triage.role = requirements.role or triage.role
        return apply_fit(triage, requirements, load_ledger(ledger_path))
    except (LedgerError, LlmError, PromptError) as error:
        triage.notes.append(f"Fit check skipped: {error}")
        return triage


def sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in SENTENCE_BREAK.split(text) if sentence.strip()]


def posting_age(text: str, today: date) -> timedelta | None:
    if match := POSTED_AGO.search(text):
        return int(match.group(1)) * AGO_UNITS[match.group(2).lower()]
    if match := POSTED_RECENT.search(text):
        return timedelta(days=1) if match.group(1).lower() == "yesterday" else timedelta(0)
    if match := POSTED_ON.search(text):
        for pattern in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                return today - datetime.strptime(match.group(1), pattern).date()
            except ValueError:
                continue
    return None


def job_board(source: str) -> str | None:
    host = urlparse(source).hostname or ""
    boards = (board for board in JOB_BOARDS if host == board or host.endswith(f".{board}"))
    return next(boards, None)


def company_from_url(source: str) -> str:
    if job_board(source):
        return ""
    parsed = urlparse(source)
    host = parsed.hostname or ""
    labels = host.removeprefix("www.").split(".")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if any(host == ats or host.endswith(f".{ats}") for ats in PATH_ATS_HOSTS) and segments:
        slug = segments[0]
    elif host.endswith(SUBDOMAIN_ATS_HOST):
        slug = labels[0]
    else:
        slug = labels[-2] if len(labels) > 1 else ""
    return slug.replace("-", " ").replace("_", " ").title()


def home_city(config: Config) -> str:
    return config.location.split(",")[0].strip()


def triage_listing(listing: Listing, config: Config, today: date | None = None) -> Triage:
    today = today or date.today()
    text = listing.text
    result = Triage(
        title=listing.title,
        company=company_from_url(listing.source),
        role=listing.title,
    )

    age = posting_age(text, today)
    if age is not None and age > STALE_AFTER:
        result.notes.append(f"Posted about {age.days} days ago (older than 72 hours).")

    if board := job_board(listing.source):
        result.notes.append(
            f"Listed on {board}. Look for the employer's own careers page and apply there."
        )

    city = home_city(config)
    near_home = city.lower() in text.lower()
    if IN_PERSON.search(text):
        if near_home:
            result.notes.append(f"Hybrid or onsite near {city}: a good sign.")
        elif not REMOTE.search(text):
            result.flags.append(f"Location: hybrid or onsite, and {city} is not mentioned.")

    authorization = []
    for sentence in sentences(text):
        if CLEARANCE.search(sentence):
            if not NEGATION.search(sentence):
                result.flags.append(f"Clearance: {sentence}")
        elif CITIZENSHIP.search(sentence):
            result.flags.append(f"Citizenship: {sentence}")
        elif WORK_AUTHORIZATION.search(sentence):
            authorization.append(sentence)
        if DEGREE.search(sentence):
            target = result.notes if PREFERRED.search(sentence) else result.flags
            target.append(f"Degree: {sentence}")

    if authorization:
        more = f" (+{len(authorization) - 1} more)" if len(authorization) > 1 else ""
        result.notes.append(f"Work authorization: {authorization[0]}{more}")
    return result
