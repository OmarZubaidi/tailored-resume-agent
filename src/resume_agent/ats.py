import re
from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_text as pdfminer_extract
from pypdf import PdfReader

from resume_agent.config import Config
from resume_agent.documents import CoverLetter, Resume, date_problems
from resume_agent.render import CONTACT_SEPARATOR_TEXT, contact_items, signature_items

REQUIRED_RESUME_HEADINGS = ("Experience", "Education", "Skills")
LAYOUT_MARKERS = {"-", CONTACT_SEPARATOR_TEXT}
LIGATURES = f"{chr(0xFB00)}-{chr(0xFB06)}"
REPLACEMENT_CHARACTER = chr(0xFFFD)
PRIVATE_USE = f"{chr(0xE000)}-{chr(0xF8FF)}"
GARBLED = re.compile(rf"[{LIGATURES}{REPLACEMENT_CHARACTER}{PRIVATE_USE}]|\(cid:\d+\)")
PHONE = re.compile(r"\(?\d{3}\)?[ .-]?\d{3}[ .-]\d{4}")


@dataclass
class Check:
    rule: str
    passed: bool
    detail: str = ""
    info: bool = False

    @property
    def result(self) -> str:
        if self.info:
            return "INFO" if self.passed else "WARN"
        return "PASS" if self.passed else "FAIL"


def resume_expected_lines(resume: Resume, config: Config) -> list[str]:
    return [config.name, *(text for text, _ in contact_items(config)), *resume.text_lines()]


def cover_letter_expected_lines(letter: CoverLetter, config: Config) -> list[str]:
    return [
        config.name,
        *(text for text, _ in contact_items(config)),
        *letter.text_lines(),
        config.name,
        *(text for text, _ in signature_items(config)),
    ]


def tokens(text: str) -> list[str]:
    return [token for token in text.split() if token not in LAYOUT_MARKERS]


def first_difference(expected: list[str], actual: list[str]) -> str:
    for index, (want, got) in enumerate(zip(expected, actual, strict=False)):
        if want != got:
            context = " ".join(expected[max(0, index - 3) : index + 3])
            return f"word {index}: expected {want!r}, got {got!r} near {context!r}"
    return f"expected {len(expected)} words, got {len(actual)}"


def round_trip_check(name: str, expected: list[str], extracted: str) -> Check:
    actual = tokens(extracted)
    if actual == expected:
        return Check(f"Text round-trips exactly ({name})", True)
    return Check(f"Text round-trips exactly ({name})", False, first_difference(expected, actual))


def check_pdf(
    pdf: Path,
    expected_lines: list[str],
    config: Config,
    required_headings: tuple[str, ...] = (),
) -> list[Check]:
    miner_text = pdfminer_extract(str(pdf))
    reader = PdfReader(str(pdf))
    pypdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    expected = tokens("\n".join(expected_lines))
    miner_lines = [line.strip() for line in miner_text.splitlines() if line.strip()]

    checks = [
        round_trip_check("pdfminer.six", expected, miner_text),
        round_trip_check("pypdf", expected, pypdf_text),
    ]

    agree = tokens(miner_text) == tokens(pypdf_text)
    checks.append(
        Check(
            "Extractors agree",
            agree,
            "" if agree else first_difference(tokens(miner_text), tokens(pypdf_text)),
        )
    )

    garbled = sorted(set(GARBLED.findall(miner_text + pypdf_text)))
    checks.append(Check("No ligatures or garbled glyphs", not garbled, ", ".join(garbled)))

    images = sum(len(page.images) for page in reader.pages)
    checks.append(Check("No images", images == 0, f"{images} found" if images else ""))

    missing = [heading for heading in required_headings if heading not in miner_lines]
    if required_headings:
        detail = f"missing: {', '.join(missing)}" if missing else ""
        checks.append(Check("Standard section headings", not missing, detail))

    email_ok = any(config.email in line for line in miner_lines)
    checks.append(Check("Email intact on one line", email_ok, "" if email_ok else config.email))
    phone_ok = any(PHONE.search(line) for line in miner_lines)
    checks.append(Check("Phone parses", phone_ok))
    location_ok = any(config.location in line for line in miner_lines)
    checks.append(Check("Location present", location_ok))

    problems = date_problems(expected_lines)
    checks.append(Check("Dates consistent and parse", not problems, "; ".join(problems)))

    pages = len(reader.pages)
    checks.append(Check("Exactly 1 page", pages == 1, "" if pages == 1 else f"{pages} pages"))
    return checks


def all_passed(checks: list[Check]) -> bool:
    return all(check.passed for check in checks if not check.info)


def report_markdown(title: str, checks: list[Check]) -> str:
    rows = [f"| {check.rule} | {check.result} | {check.detail} |" for check in checks]
    verdict = "PASS" if all_passed(checks) else "FAIL"
    return "\n".join(
        [
            f"# ATS report: {title}",
            "",
            f"Overall: **{verdict}**",
            "",
            "| Rule | Result | Detail |",
            "|---|---|---|",
            *rows,
            "",
        ]
    )
