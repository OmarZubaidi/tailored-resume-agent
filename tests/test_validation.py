from pathlib import Path

import pytest

from resume_agent.job_listing import LISTING_MD, Listing, ListingError, read_listing
from resume_agent.validation import (
    MIN_WORDS,
    SOFT_MIN_WORDS,
    Tier,
    agreement,
    resolve_listing,
    validate_text,
    word_count,
)

TITLE = "Senior Software Engineer"


def listing_text(words: int, sections: str = "Responsibilities Requirements") -> str:
    header = f"{TITLE} {sections}"
    filler = " ".join("word" for _ in range(words - word_count(header)))
    return f"{header} {filler}"


def test_word_count_keeps_tech_terms_whole():
    assert word_count("C# and Node.js, CI/CD, don’t") == 5


@pytest.mark.parametrize(
    ("words", "tier"),
    [
        (SOFT_MIN_WORDS, Tier.ACCEPT),
        (SOFT_MIN_WORDS - 1, Tier.CONFIRM_WITH_OCR),
        (MIN_WORDS, Tier.CONFIRM_WITH_OCR),
        (MIN_WORDS - 1, Tier.RECOVER_WITH_OCR),
    ],
)
def test_tiers_by_word_count(words, tier):
    result = validate_text(TITLE, listing_text(words))

    assert result.words == words
    assert result.tier is tier


def test_missing_title_needs_recovery():
    result = validate_text("Staff Data Scientist", listing_text(SOFT_MIN_WORDS))

    assert not result.has_title
    assert result.tier is Tier.RECOVER_WITH_OCR


def test_no_section_signals_needs_recovery():
    result = validate_text(TITLE, listing_text(SOFT_MIN_WORDS, sections="Apply now"))

    assert result.sections == []
    assert result.tier is Tier.RECOVER_WITH_OCR


def test_title_match_is_case_insensitive():
    result = validate_text(TITLE, listing_text(SOFT_MIN_WORDS).lower())

    assert result.has_signals


def make_listing(text: str) -> Listing:
    return Listing(source="https://example.com/job", title=TITLE, text=text)


def fail_ocr(_: Path) -> str:
    raise AssertionError("OCR should not run")


def test_long_listing_skips_ocr(tmp_path):
    listing = make_listing(listing_text(SOFT_MIN_WORDS))

    resolved, validation, used_ocr = resolve_listing(listing, tmp_path, ocr=fail_ocr)

    assert resolved == listing
    assert validation.tier is Tier.ACCEPT
    assert not used_ocr


def test_short_listing_accepted_when_ocr_agrees(tmp_path):
    text = listing_text(MIN_WORDS + 10)

    resolved, _, used_ocr = resolve_listing(make_listing(text), tmp_path, ocr=lambda _: text)

    assert resolved.text == text
    assert used_ocr


def test_short_listing_rejected_when_ocr_disagrees(tmp_path):
    listing = make_listing(listing_text(MIN_WORDS + 10))

    with pytest.raises(ListingError, match="OCR agrees with only 0%.*--pdf"):
        resolve_listing(listing, tmp_path, ocr=lambda _: "something else entirely")


def test_empty_page_recovered_from_ocr(tmp_path):
    ocr_text = listing_text(SOFT_MIN_WORDS)

    resolved, validation, used_ocr = resolve_listing(
        make_listing("Loading..."), tmp_path, ocr=lambda _: ocr_text
    )

    assert resolved.text == ocr_text
    assert validation.tier is Tier.ACCEPT
    assert used_ocr
    assert read_listing(tmp_path / LISTING_MD).text == ocr_text


def test_unrecoverable_listing_asks_for_pdf(tmp_path):
    with pytest.raises(ListingError, match="3 words.*Print the page to PDF"):
        resolve_listing(make_listing("Loading..."), tmp_path, ocr=lambda _: "Please sign in")


def test_unrecoverable_supplied_pdf_asks_to_check_it(tmp_path):
    listing = Listing(source="file: printed.pdf", title=TITLE, text="Loading...")

    with pytest.raises(ListingError, match="Check the PDF holds the full listing"):
        resolve_listing(listing, tmp_path, ocr=lambda _: "Please sign in")


def test_ocr_failure_is_a_listing_error(tmp_path):
    def broken_ocr(_: Path) -> str:
        raise RuntimeError("Vision unavailable")

    with pytest.raises(ListingError, match="OCR failed on listing.pdf: Vision unavailable"):
        resolve_listing(make_listing("Loading..."), tmp_path, ocr=broken_ocr)


@pytest.mark.parametrize(
    ("extracted", "ocr_text", "expected"),
    [
        ("Build React apps", "build react apps", 1.0),
        ("Build React apps now", "Build React", 0.5),
        ("", "anything", 0.0),
    ],
)
def test_agreement(extracted, ocr_text, expected):
    assert agreement(extracted, ocr_text) == expected
