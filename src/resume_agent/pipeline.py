import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from pypdf import PdfReader

from resume_agent.ats import (
    REQUIRED_RESUME_HEADINGS,
    Check,
    all_passed,
    check_pdf,
    cover_letter_expected_lines,
    report_markdown,
    resume_expected_lines,
)
from resume_agent.browser import BrowserError
from resume_agent.config import Config
from resume_agent.cover_letter import write_cover_letter
from resume_agent.data_root import BASELINES_DIR
from resume_agent.documents import (
    DocumentError,
    Resume,
    open_placeholders,
    parse_cover_letter,
    parse_resume,
    resume_markdown,
)
from resume_agent.guards.rules import (
    DRAFTS_DIR,
    NOTES_FILE,
    GuardError,
    is_locked,
    lock_applied_files,
    require_files,
)
from resume_agent.job_listing import LISTING_MD, Listing, read_listing
from resume_agent.keywords import coverage_detail, keyword_coverage, mentions
from resume_agent.ledger import LEDGER_FILE, LedgerError, load_ledger
from resume_agent.llm import LlmError
from resume_agent.prompts import PromptError, parse_json_reply, render_prompt
from resume_agent.render import RenderError, cover_letter_html, render_pdf, resume_html
from resume_agent.tailor import (
    BANK_FILE,
    TailorError,
    apply_plan,
    bank_markdown,
    build_bank,
    diff_markdown,
    drop_lowest_bullet,
    experience_roles,
    ledger_summary,
    without_roles,
)
from resume_agent.triage import (
    TRIAGE_MD,
    Triage,
    add_fit,
    listing_years_max,
    save_years,
    triage_listing,
)

TAILOR_ERRORS = (
    BrowserError,
    DocumentError,
    FileNotFoundError,
    LedgerError,
    LlmError,
    PromptError,
    RenderError,
    TailorError,
)
RESUME_DOCUMENT = "Resume"
COVER_LETTER_DOCUMENT = "Cover-Letter"
RESUME_SOURCE = "resume.md"
COVER_LETTER_SOURCE = "cover-letter.md"
ATS_REPORT = "ats-report.md"
DIFF_FILE = "diff.md"
TAILORING_RULES = "tailoring-rules.md"
VOICE_FILE = "style/voice.md"
NO_EXTRA_RULES = "None."


class Mode(StrEnum):
    UPWARD = "upward"
    LATERAL = "lateral"


@dataclass
class RenderResult:
    resume_pdf: Path
    cover_letter_pdf: Path
    report: Path
    passed: bool


def pdf_name(person: str, document: str) -> str:
    return f"{re.sub(r'\s+', '-', person.strip())}-{document}.pdf"


def baseline_dir(config: Config, baseline: str) -> Path:
    return config.data_root / BASELINES_DIR / baseline


def triage_folder(
    listing: Listing,
    folder: Path,
    config: Config,
    run: Callable[[str], str],
    baseline: str | None = None,
) -> Triage:
    triage = triage_listing(listing, config)
    ledger_path = baseline_dir(config, baseline or config.default_baseline) / LEDGER_FILE
    add_fit(triage, listing.text, ledger_path, run)
    (folder / TRIAGE_MD).write_text(triage.markdown())
    save_years(folder, triage)
    return triage


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
    resume_pdf = folder / pdf_name(config.name, RESUME_DOCUMENT)
    letter_pdf = folder / pdf_name(config.name, COVER_LETTER_DOCUMENT)

    render_pdf(resume_html(resume, config), resume_pdf)
    render_pdf(cover_letter_html(letter, config), letter_pdf)
    passed = write_ats_report(folder, config)
    return RenderResult(resume_pdf, letter_pdf, report, passed)


def write_ats_report(folder: Path, config: Config) -> bool:
    resume = parse_resume((folder / RESUME_SOURCE).read_text())
    letter = parse_cover_letter((folder / COVER_LETTER_SOURCE).read_text())
    resume_pdf = folder / pdf_name(config.name, RESUME_DOCUMENT)
    letter_pdf = folder / pdf_name(config.name, COVER_LETTER_DOCUMENT)
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
    (folder / ATS_REPORT).write_text(
        report_markdown(resume_pdf.name, resume_checks)
        + "\n"
        + report_markdown(letter_pdf.name, letter_checks)
    )
    return all_passed(resume_checks + letter_checks)


def applied_files(config: Config) -> list[str]:
    return [
        RESUME_SOURCE,
        COVER_LETTER_SOURCE,
        pdf_name(config.name, RESUME_DOCUMENT),
        pdf_name(config.name, COVER_LETTER_DOCUMENT),
    ]


def lock_application(
    folder: Path,
    config: Config,
    today: date,
    resume_file: Path | None = None,
    letter_file: Path | None = None,
) -> bool:
    handed = {
        folder / pdf_name(config.name, document): source
        for document, source in (
            (RESUME_DOCUMENT, resume_file),
            (COVER_LETTER_DOCUMENT, letter_file),
        )
        if source is not None
    }
    locked = [target.name for target in handed if is_locked(target)]
    if locked:
        raise GuardError(f"Already locked, it was applied with before: {', '.join(locked)}")
    notes = []
    for target, source in handed.items():
        shutil.copyfile(source, target)
        notes.append(f"- {today.isoformat()} `{target.name}` replaced with `{source.name}`\n")
    with (folder / NOTES_FILE).open("a") as file:
        file.writelines(notes)
    require_files(folder, applied_files(config))

    passed = write_ats_report(folder, config)
    lock_applied_files(folder, applied_files(config), today)
    return passed


@dataclass
class TailorResult:
    folder: Path
    mode: Mode
    flags: list[str]
    render: RenderResult


def output_folder(folder: Path) -> Path:
    if not any(is_locked(folder / name) for name in (RESUME_SOURCE, COVER_LETTER_SOURCE)):
        return folder
    drafts = folder / DRAFTS_DIR
    drafts.mkdir(exist_ok=True)
    (drafts / LISTING_MD).write_text((folder / LISTING_MD).read_text())
    return drafts


def optional_text(path: Path, fallback: str) -> str:
    return path.read_text().strip() if path.is_file() else fallback


def detect_mode(listing_text: str, config: Config) -> Mode:
    keywords = config.industry_keywords.get(config.home_industry, [])
    return Mode.UPWARD if any(mentions(term, listing_text) for term in keywords) else Mode.LATERAL


def junior_companies(
    folder: Path, listing_text: str, config: Config, run: Callable[[str], str]
) -> list[str]:
    junior = config.junior_listing
    if not junior.drop_companies:
        return []
    years_max = listing_years_max(folder, listing_text, run)
    if years_max is None or years_max > junior.max_years:
        return []
    return junior.drop_companies


def unmatched_drop_companies(config: Config) -> list[str]:
    companies = {
        role.company.lower()
        for path in (config.data_root / BASELINES_DIR).glob(f"*/{RESUME_SOURCE}")
        for role in experience_roles(parse_resume(path.read_text()))
    }
    return [
        company
        for company in config.junior_listing.drop_companies
        if company.lower() not in companies
    ]


def junior_drops(
    resume: Resume, folder: Path, listing_text: str, config: Config, run: Callable[[str], str]
) -> tuple[list[str], list[str]]:
    try:
        companies = junior_companies(folder, listing_text, config, run)
    except (LlmError, PromptError) as error:
        return [], [f"Junior listing check skipped: {error}"]
    kept = experience_roles(without_roles(resume, companies))
    removed = [role.company for role in experience_roles(resume) if role not in kept]
    if not removed:
        return [], []
    max_years = config.junior_listing.max_years
    return companies, [
        f"Dropped for a listing capped at {max_years} years or fewer: {', '.join(removed)}"
    ]


def notes_markdown(baseline: str, mode: Mode, config: Config, today: date) -> str:
    return "\n".join(
        [
            "# Notes",
            "",
            f"- Tailored: {today.isoformat()}",
            f"- Baseline: {baseline}",
            f"- Mode: {mode.value}",
            f"- Provider: {config.llm.provider.value} ({config.llm.model or 'default model'})",
            "",
        ]
    )


def tailor_folder(
    folder: Path,
    config: Config,
    run: Callable[[str], str],
    baseline: str | None = None,
    mode: Mode | None = None,
    today: date | None = None,
) -> TailorResult:
    baseline = baseline or config.default_baseline
    source = baseline_dir(config, baseline)
    listing = read_listing(folder / LISTING_MD)
    ledger = load_ledger(source / LEDGER_FILE)
    full_resume = parse_resume((source / RESUME_SOURCE).read_text())
    dropped, junior_flags = junior_drops(full_resume, folder, listing.text, config, run)
    baseline_resume = without_roles(full_resume, dropped)
    bank_path = source / BANK_FILE
    extra = (
        without_roles(parse_resume(bank_path.read_text()), dropped) if bank_path.is_file() else None
    )
    bank = build_bank(baseline_resume, extra)
    mode = mode or detect_mode(listing.text, config)

    prompt = render_prompt(
        "tailor-resume",
        mode=mode.value,
        home_industry=config.home_industry,
        industry_keywords=", ".join(config.industry_keywords.get(config.home_industry, [])),
        listing=listing.text,
        baseline=resume_markdown(baseline_resume),
        bullet_bank=bank_markdown(bank),
        ledger=ledger_summary(ledger),
        tailoring_rules=optional_text(config.data_root / TAILORING_RULES, NO_EXTRA_RULES),
    )
    tailored = apply_plan(parse_json_reply(run(prompt)), baseline_resume, bank, ledger)
    tailored.flags.extend(junior_flags)
    letter = write_cover_letter(
        run,
        listing.text,
        listing.title,
        resume_markdown(tailored.resume),
        (source / COVER_LETTER_SOURCE).read_text(),
        ledger,
        optional_text(config.data_root / VOICE_FILE, ""),
    )

    out = output_folder(folder)
    (out / RESUME_SOURCE).write_text(resume_markdown(tailored.resume))
    (out / COVER_LETTER_SOURCE).write_text(letter.markdown)
    render = render_folder(out, config)
    while page_count(render.resume_pdf) > 1 and drop_lowest_bullet(tailored):
        (out / RESUME_SOURCE).write_text(resume_markdown(tailored.resume))
        render = render_folder(out, config)
    if page_count(render.resume_pdf) > 1:
        tailored.flags.append("Still over one page after trimming every role to 2 bullets")

    tailored.flags.extend(letter.flags)
    (out / DIFF_FILE).write_text(diff_markdown(baseline_resume, tailored, bank))
    (out / NOTES_FILE).write_text(notes_markdown(baseline, mode, config, today or date.today()))
    return TailorResult(folder=out, mode=mode, flags=tailored.flags, render=render)


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)
