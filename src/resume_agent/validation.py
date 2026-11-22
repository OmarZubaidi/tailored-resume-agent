import re
from dataclasses import dataclass
from enum import StrEnum

from resume_agent.job_listing import Listing

# The shortest real contract listing sampled was ~63 words, minus ~10%.
MIN_WORDS = 55
# A study of 29k listings found a median of 412 words and a 25th percentile of 267.
SOFT_MIN_WORDS = 300
SECTION_SIGNALS = ("responsibilities", "requirements", "qualifications", "skills", "experience")


class Tier(StrEnum):
    ACCEPT = "accept"
    CONFIRM_WITH_OCR = "confirm with OCR"
    RECOVER_WITH_OCR = "recover with OCR"


@dataclass
class Validation:
    words: int
    has_title: bool
    sections: list[str]
    tier: Tier

    @property
    def has_signals(self) -> bool:
        return self.has_title and bool(self.sections)


def word_count(text: str) -> int:
    return len(re.findall(r"\w[\w'’+#./-]*", text))


def validate_text(title: str, text: str) -> Validation:
    lowered = text.lower()
    words = word_count(text)
    has_title = bool(title.strip()) and title.strip().lower() in lowered
    sections = [signal for signal in SECTION_SIGNALS if signal in lowered]

    if not (has_title and sections) or words < MIN_WORDS:
        tier = Tier.RECOVER_WITH_OCR
    elif words < SOFT_MIN_WORDS:
        tier = Tier.CONFIRM_WITH_OCR
    else:
        tier = Tier.ACCEPT
    return Validation(words=words, has_title=has_title, sections=sections, tier=tier)


def validate_listing(listing: Listing) -> Validation:
    return validate_text(listing.title, listing.text)
