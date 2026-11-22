import re
from dataclasses import dataclass
from pathlib import Path

from resume_agent.ats import (
    REQUIRED_RESUME_HEADINGS,
    Check,
    all_passed,
    check_pdf,
    cover_letter_expected_lines,
    report_markdown,
    resume_expected_lines,
)
from resume_agent.config import Config
from resume_agent.documents import (
    DocumentError,
    open_placeholders,
    parse_cover_letter,
    parse_resume,
)
from resume_agent.job_listing import LISTING_MD, read_listing
from resume_agent.keywords import coverage_detail, keyword_coverage
from resume_agent.render import cover_letter_html, render_pdf, resume_html

RESUME_SOURCE = "resume.md"
COVER_LETTER_SOURCE = "cover-letter.md"
ATS_REPORT = "ats-report.md"


@dataclass
class RenderResult:
    resume_pdf: Path
    cover_letter_pdf: Path
    report: Path
    passed: bool


def pdf_name(person: str, document: str) -> str:
    return f"{re.sub(r'\s+', '-', person.strip())}-{document}.pdf"


def baseline_dir(config: Config, baseline: str) -> Path:
    return config.data_root / "baselines" / baseline


def render_folder(folder: Path, config: Config, draft: bool = False) -> RenderResult:
    report = folder / ATS_REPORT
    report.unlink(missing_ok=True)
    resume = parse_resume((folder / RESUME_SOURCE).read_text())
    letter = parse_cover_letter((folder / COVER_LETTER_SOURCE).read_text())
    placeholders = open_placeholders(resume.text_lines() + letter.text_lines())
    if placeholders and not draft:
        raise DocumentError(
            f"Fill these placeholders before rendering: {', '.join(placeholders)}. "
            "Use --draft to render a template anyway."
        )
    resume_pdf = folder / pdf_name(config.name, "Resume")
    letter_pdf = folder / pdf_name(config.name, "Cover-Letter")

    render_pdf(resume_html(resume, config), resume_pdf)
    render_pdf(cover_letter_html(letter, config), letter_pdf)

    resume_checks: list[Check] = check_pdf(
        resume_pdf, resume_expected_lines(resume, config), config, REQUIRED_RESUME_HEADINGS
    )
    listing_md = folder / LISTING_MD
    if listing_md.exists():
        coverage = keyword_coverage(read_listing(listing_md).text, resume, config)
        resume_checks.append(
            Check(
                "Keyword coverage vs listing",
                not coverage.stuffed,
                coverage_detail(coverage),
                info=True,
            )
        )
    letter_checks = check_pdf(letter_pdf, cover_letter_expected_lines(letter, config), config)
    report.write_text(
        report_markdown(resume_pdf.name, resume_checks)
        + "\n"
        + report_markdown(letter_pdf.name, letter_checks)
    )
    passed = all_passed(resume_checks + letter_checks)
    return RenderResult(resume_pdf, letter_pdf, report, passed)
