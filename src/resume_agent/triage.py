import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from resume_agent.config import Config
from resume_agent.job_listing import Listing

TRIAGE_MD = "triage.md"
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

    @property
    def flagged(self) -> bool:
        return bool(self.flags)

    def markdown(self) -> str:
        lines = [
            f"# Triage: {self.title}",
            "",
            f"Result: **{'FLAGGED' if self.flagged else 'CLEAR'}**",
            "",
            "## Flags",
            *(f"- {flag}" for flag in self.flags or ["None"]),
            "",
            "## Notes",
            *(f"- {note}" for note in self.notes or ["None"]),
            "",
            "## Pending",
            "- Years of experience and skills fit against the skills ledger.",
            "",
        ]
        return "\n".join(lines)


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


def home_city(config: Config) -> str:
    return config.location.split(",")[0].strip()


def triage_listing(listing: Listing, config: Config, today: date | None = None) -> Triage:
    today = today or date.today()
    text = listing.text
    result = Triage(title=listing.title)

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
