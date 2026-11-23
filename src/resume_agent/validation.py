import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from resume_agent.browser import BrowserError
from resume_agent.job_listing import (
    LISTING_PDF,
    PDF_SOURCE_PREFIX,
    Listing,
    ListingError,
    clean_text,
    fetch_listing,
    save_listing,
)
from resume_agent.ocr import ocr_pdf

# The shortest real contract listing sampled was ~63 words, minus ~10%.
MIN_WORDS = 55
# A study of 29k listings found a median of 412 words and a 25th percentile of 267.
SOFT_MIN_WORDS = 300
OCR_AGREEMENT = 0.8
SECTION_SIGNALS = ("responsibilities", "requirements", "qualifications", "skills", "experience")
WORD = re.compile(r"\w[\w'’+#./-]*")
FETCH_ERRORS = (BrowserError, ListingError)


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
    return len(WORD.findall(text))


def words(text: str) -> set[str]:
    return {word.lower() for word in WORD.findall(text)}


def agreement(extracted: str, ocr_text: str) -> float:
    expected = words(extracted)
    if not expected:
        return 0.0
    return len(expected & words(ocr_text)) / len(expected)


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


def unusable(listing: Listing, reason: str) -> ListingError:
    if listing.source.startswith(PDF_SOURCE_PREFIX):
        advice = "Check the PDF holds the full listing text, then pass it again."
    else:
        advice = "Print the page to PDF and pass it with --pdf."
    return ListingError(f"Couldn't get a usable listing from {listing.source} ({reason}). {advice}")


def run_ocr(ocr: Callable[[Path], str], pdf: Path) -> str:
    try:
        return clean_text(ocr(pdf))
    except Exception as error:
        raise ListingError(f"OCR failed on {pdf.name}: {error}") from error


def resolve_listing(
    listing: Listing,
    out_dir: Path,
    ocr: Callable[[Path], str] = ocr_pdf,
) -> tuple[Listing, Validation, bool]:
    validation = validate_listing(listing)
    if validation.tier is Tier.ACCEPT:
        return listing, validation, False

    ocr_text = run_ocr(ocr, out_dir / LISTING_PDF)
    if validation.tier is Tier.CONFIRM_WITH_OCR:
        score = agreement(listing.text, ocr_text)
        if score < OCR_AGREEMENT:
            raise unusable(listing, f"OCR agrees with only {score:.0%} of the page text")
        return listing, validation, True

    recovered = replace(listing, text=ocr_text)
    recovered_validation = validate_listing(recovered)
    if recovered_validation.tier is Tier.RECOVER_WITH_OCR:
        raise unusable(
            listing,
            f"{recovered_validation.words} words, title found: {recovered_validation.has_title}, "
            f"sections: {', '.join(recovered_validation.sections) or 'none'}",
        )
    save_listing(recovered, out_dir)
    return recovered, recovered_validation, True


def fetch_usable_listing(url: str, out_dir: Path) -> tuple[Listing, Validation, bool]:
    try:
        return resolve_listing(fetch_listing(url, out_dir), out_dir)
    except FETCH_ERRORS as error:
        headless_error = error
    try:
        return resolve_listing(fetch_listing(url, out_dir, chrome=True), out_dir)
    except FETCH_ERRORS as error:
        raise ListingError(f"{headless_error} | Chrome also failed: {error}") from error
