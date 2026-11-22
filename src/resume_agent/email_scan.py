from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from resume_agent.gmail import Email
from resume_agent.prompts import PromptError, parse_json_reply, render_prompt, text_value

MAX_EMAIL_CHARACTERS = 8_000


class EmailKind(StrEnum):
    REJECTION = "rejection"
    INTERVIEW = "interview"
    OFFER = "offer"
    OTHER = "other"


@dataclass(frozen=True)
class Classification:
    kind: EmailKind
    company: str
    role: str
    interview_date: date | None


def iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def classify_email(run: Callable[[str], str], email: Email) -> Classification:
    prompt = render_prompt(
        "classify-email",
        received=email.received.isoformat(),
        sender=email.sender,
        subject=email.subject,
        body=email.text[:MAX_EMAIL_CHARACTERS],
    )
    data = parse_json_reply(run(prompt))
    try:
        kind = EmailKind(data.get("kind"))
    except ValueError as error:
        raise PromptError(f"Unknown email kind from the model: {data.get('kind')!r}") from error
    return Classification(
        kind=kind,
        company=text_value(data.get("company")),
        role=text_value(data.get("role")),
        interview_date=iso_date(data.get("interview_date"))
        if kind == EmailKind.INTERVIEW
        else None,
    )
