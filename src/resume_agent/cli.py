import subprocess
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from resume_agent.application_folder import application_dir, format_id
from resume_agent.browser import BrowserError
from resume_agent.config import Config, ConfigError, load_config
from resume_agent.data_root import dataless_paths, dataless_warning, init_data_root
from resume_agent.documents import DocumentError
from resume_agent.email_scan import (
    ScanError,
    describe_update,
    notification,
    notify,
    scan_mailbox,
)
from resume_agent.gmail import GmailError, open_mailbox
from resume_agent.gmail import login as gmail_sign_in
from resume_agent.guards.rules import GuardError, ensure_excel_closed
from resume_agent.inbox import Decision, InboxError, InboxResult, process_inbox, review_rows
from resume_agent.job_listing import ListingError, fetch_listing, listing_from_pdf
from resume_agent.llm import LlmError, run_prompt
from resume_agent.pipeline import (
    DIFF_FILE,
    TAILOR_ERRORS,
    Mode,
    baseline_dir,
    lock_application,
    render_folder,
    tailor_folder,
    triage_folder,
)
from resume_agent.prompts import PromptError
from resume_agent.render import RenderError
from resume_agent.stages import (
    Ambiguous,
    StageError,
    add_stage_event,
    find_application,
    load_variants,
    pick_line,
    record_stage,
)
from resume_agent.tracker import (
    InboxRow,
    Stage,
    Tracker,
    TrackerError,
    check_saveable,
    init_workbook,
    load_tracker,
    save_tracker,
    workbook_path,
)
from resume_agent.triage import TRIAGE_MD
from resume_agent.validation import resolve_listing

app = typer.Typer(help="Tailored Resume and Application Agent", no_args_is_help=True)
config_app = typer.Typer(help="Inspect the config file.", no_args_is_help=True)
app.add_typer(config_app, name="config")
dev_app = typer.Typer(help="Developer setup.", no_args_is_help=True)
app.add_typer(dev_app, name="dev")
gmail_app = typer.Typer(help="Read-only Gmail sign-in and scan.", no_args_is_help=True)
app.add_typer(gmail_app, name="gmail")
HOOKS_PATH = ".githooks"
ISO_DATE = "%Y-%m-%d"


@app.callback()
def main() -> None:
    pass


def load_config_or_exit() -> Config:
    try:
        return load_config()
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


def llm_runner(config: Config) -> Callable[[str], str]:
    return lambda prompt: run_prompt(config, prompt)


@config_app.command("check")
def config_check() -> None:
    """Validate the config file."""
    config = load_config_or_exit()
    typer.echo(f"Config OK. data_root: {config.data_root}")


@app.command("init")
def init() -> None:
    """Create the data folder layout under data_root."""
    config = load_config_or_exit()
    cloud_only = dataless_paths(config.data_root)
    if cloud_only:
        typer.echo(dataless_warning(cloud_only), err=True)
        raise typer.Exit(1)

    created = init_data_root(config.data_root)
    try:
        workbook = init_workbook(config)
    except (GuardError, TrackerError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    for path in [*created, *([workbook] if workbook else [])]:
        typer.echo(f"Created {path}")
    typer.echo(f"Data root ready: {config.data_root}")


@app.command("render")
def render(
    folder: Annotated[
        Path | None, typer.Argument(help="Folder with resume.md and cover-letter.md.")
    ] = None,
    baseline: Annotated[
        str | None, typer.Option(help="Baseline name; defaults to default_baseline.")
    ] = None,
    draft: Annotated[bool, typer.Option(help="Render even with open [placeholders].")] = False,
) -> None:
    """Render resume and cover letter PDFs and write the ATS report."""
    if folder and baseline:
        typer.echo("Pass a folder or --baseline, not both.", err=True)
        raise typer.Exit(1)
    config = load_config_or_exit()
    source = folder or baseline_dir(config, baseline or config.default_baseline)
    try:
        result = render_folder(source, config, draft=draft)
    except (BrowserError, DocumentError, RenderError, FileNotFoundError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    typer.echo(f"Wrote {result.resume_pdf}\nWrote {result.cover_letter_pdf}")
    typer.echo(f"ATS {'PASS' if result.passed else 'FAIL'}: {result.report}")
    if not result.passed:
        raise typer.Exit(1)


@app.command("fetch")
def fetch(
    out_dir: Annotated[Path, typer.Argument(help="Folder for listing.pdf, listing.md, triage.md.")],
    url: Annotated[str | None, typer.Option(help="Job listing URL.")] = None,
    pdf: Annotated[Path | None, typer.Option(help="A listing you printed to PDF.")] = None,
    baseline: Annotated[
        str | None, typer.Option(help="Baseline whose skills ledger the fit check uses.")
    ] = None,
) -> None:
    """Save a job listing, validate it and triage it."""
    if (url is None) == (pdf is None):
        typer.echo("Pass exactly one of --url or --pdf.", err=True)
        raise typer.Exit(1)
    config = load_config_or_exit()
    try:
        raw = fetch_listing(url, out_dir) if url else listing_from_pdf(pdf, out_dir)
        listing, validation, used_ocr = resolve_listing(raw, out_dir)
    except (BrowserError, ListingError, FileNotFoundError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    triage = triage_folder(listing, out_dir, config, llm_runner(config), baseline)
    typer.echo(f"Listing: {listing.title} ({validation.words} words{', OCR' if used_ocr else ''})")
    typer.echo(f"Triage {'FLAGGED' if triage.flagged else 'CLEAR'}: {out_dir / TRIAGE_MD}")


@app.command("tailor")
def tailor(
    folder: Annotated[Path, typer.Argument(help="Folder holding listing.md from fetch.")],
    baseline: Annotated[
        str | None, typer.Option(help="Baseline name; defaults to default_baseline.")
    ] = None,
    mode: Annotated[
        Mode | None, typer.Option(help="upward or lateral; detected from the listing if unset.")
    ] = None,
) -> None:
    """Tailor the resume and cover letter to a listing, then render them."""
    config = load_config_or_exit()
    try:
        result = tailor_folder(folder, config, llm_runner(config), baseline, mode)
    except TAILOR_ERRORS as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    typer.echo(f"Tailored ({result.mode.value}): {result.folder / DIFF_FILE}")
    for flag in result.flags:
        typer.echo(f"  Review: {flag}")
    typer.echo(f"ATS {'PASS' if result.render.passed else 'FAIL'}: {result.render.report}")
    if not result.render.passed:
        raise typer.Exit(1)


def today() -> date:
    return date.today()


def open_tracker(config: Config) -> Tracker:
    path = workbook_path(config.data_root)
    ensure_excel_closed(path)
    return load_tracker(path)


def flagged_line(row: InboxRow) -> str:
    return f"  {format_id(row.id)}  {row.company} - {row.role}: {row.reason}"


@app.command("inbox")
def inbox() -> None:
    """Fetch, triage and tailor every new URL in the Inbox sheet."""
    config = load_config_or_exit()
    try:
        tracker = open_tracker(config)
        result = process_inbox(
            tracker,
            config,
            llm_runner(config),
            today(),
            save=lambda: save_tracker(tracker, config),
            report=typer.echo,
        )
    except (GuardError, TrackerError) as error:
        typer.echo(f"{error}\nProgress up to the last finished step is saved.", err=True)
        raise typer.Exit(1) from error
    echo_inbox_result(result)


@app.command("review")
def review(
    decision: Annotated[Decision, typer.Argument(help="proceed tailors, drop marks Skipped.")],
    application_ids: Annotated[list[int], typer.Argument(help="IDs from the flagged list.")],
) -> None:
    """Proceed with or drop flagged Inbox jobs."""
    config = load_config_or_exit()
    try:
        tracker = open_tracker(config)
        result = review_rows(
            tracker,
            application_ids,
            decision,
            config,
            llm_runner(config),
            today(),
            save=lambda: save_tracker(tracker, config),
        )
    except (GuardError, InboxError, TrackerError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    echo_inbox_result(result)


def echo_inbox_result(result: InboxResult) -> None:
    for application in result.tailored:
        suffix = f" ({application.notes})" if application.notes else ""
        typer.echo(f"{application.status}: {pick_line(application)}{suffix}")
    for row in result.failed:
        typer.echo(f"Failed {row.url}: {row.reason}", err=True)
    if result.flagged:
        lines = "\n".join(flagged_line(row) for row in result.flagged)
        typer.echo(f"Flagged, waiting for your review:\n{lines}")
        typer.echo("Decide with: resume_agent review proceed|drop <ID>...")
    if result.failed:
        raise typer.Exit(1)


@app.command("update")
def update(
    company: Annotated[str, typer.Argument(help="Company name, or a variant in companies.yaml.")],
    stage: Annotated[Stage, typer.Argument(case_sensitive=False, help="Stage reached.")],
    day: Annotated[
        datetime | None,
        typer.Option("--date", formats=[ISO_DATE], help="Stage date; defaults to today."),
    ] = None,
    note: Annotated[str | None, typer.Option(help="Detail for timeline.md.")] = None,
    title: Annotated[str | None, typer.Option(help="Job title, when several are open.")] = None,
    application_id: Annotated[
        int | None, typer.Option("--id", help="Application ID from the pick list.")
    ] = None,
    resume_file: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="Applied with this resume PDF instead."),
    ] = None,
    letter_file: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="Applied with this cover letter instead."),
    ] = None,
) -> None:
    """Record a stage (Applied, 1st, 2nd, 3rd, Offer, Rejected, Skipped) for an application.

    Applied locks the resume and cover letter in the application folder.
    """
    if (resume_file or letter_file) and stage != Stage.APPLIED:
        typer.echo("--resume-file and --letter-file only go with Applied.", err=True)
        raise typer.Exit(1)
    config = load_config_or_exit()
    ats_passed = None
    try:
        tracker = open_tracker(config)
        variants = load_variants(config.data_root)
        application = find_application(tracker, company, variants, title, application_id)
        stage_day = day.date() if day else today()
        record_stage(application, stage, stage_day)
        folder = application_dir(config.data_root, application)
        if (resume_file or letter_file) and not folder:
            raise StageError(f"{pick_line(application)} has no folder for the handed-over files")
        check_saveable(tracker, workbook_path(config.data_root))
        if stage == Stage.APPLIED and folder:
            ats_passed = lock_application(folder, config, stage_day, resume_file, letter_file)
        save_tracker(tracker, config)
        add_stage_event(application, stage, stage_day, config.data_root, note)
    except Ambiguous as ambiguous:
        lines = "\n".join(f"  {pick_line(app)}" for app in ambiguous.candidates)
        typer.echo(f"Several open applications match {company}:\n{lines}", err=True)
        typer.echo("Rerun with --id <ID>.", err=True)
        raise typer.Exit(1) from ambiguous
    except (DocumentError, GuardError, StageError, TrackerError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    typer.echo(f"{pick_line(application)}: {stage.value} {stage_day}")
    if ats_passed is not None:
        typer.echo(f"Locked applied files. ATS {'PASS' if ats_passed else 'FAIL'}")
    elif stage == Stage.APPLIED:
        typer.echo("No application folder, so no files were locked.", err=True)


@gmail_app.command("login")
def gmail_login(
    client_file: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Desktop OAuth client JSON from Google."),
    ],
) -> None:
    """Sign in to Gmail read-only and keep the token in the macOS Keychain."""
    config = load_config_or_exit()
    try:
        account = gmail_sign_in(client_file, config)
    except GmailError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Signed in to Gmail as {account}. The token is in the Keychain.")


SCAN_ERRORS = (GmailError, LlmError, PromptError, ScanError, StageError, TrackerError)


@gmail_app.command("scan")
def gmail_scan() -> None:
    """Classify new application emails and queue proposed stage updates for review."""
    config = load_config_or_exit()
    try:
        mailbox = open_mailbox(config)
        tracker = load_tracker(workbook_path(config.data_root))
        variants = load_variants(config.data_root)
        run = llm_runner(config)
        added = scan_mailbox(mailbox, tracker, variants, run, config.data_root, datetime.now())
    except SCAN_ERRORS as error:
        typer.echo(str(error), err=True)
        summary = str(error).partition("\n")[0]
        notify(f"Gmail scan failed: {summary}")
        raise typer.Exit(1) from error
    for update in added:
        typer.echo(describe_update(update, tracker))
    if added:
        notify(notification(added))


@dev_app.command("install-hooks")
def install_hooks() -> None:
    """Point git at the repo's hooks so the pre-commit guard runs."""
    result = subprocess.run(
        ["git", "config", "core.hooksPath", HOOKS_PATH],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Run this inside the repo. git said: {result.stderr.strip()}", err=True)
        raise typer.Exit(1)
    typer.echo(f"core.hooksPath set to {HOOKS_PATH}")
