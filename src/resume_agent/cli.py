import subprocess
from pathlib import Path
from typing import Annotated

import typer

from resume_agent.browser import BrowserError
from resume_agent.config import Config, ConfigError, load_config
from resume_agent.data_root import dataless_paths, dataless_warning, init_data_root
from resume_agent.documents import DocumentError
from resume_agent.guards.rules import GuardError
from resume_agent.job_listing import ListingError, fetch_listing, listing_from_pdf
from resume_agent.ledger import LEDGER_FILE, LedgerError
from resume_agent.llm import LlmError, run_prompt
from resume_agent.pipeline import DIFF_FILE, Mode, baseline_dir, render_folder, tailor_folder
from resume_agent.prompts import PromptError
from resume_agent.render import RenderError
from resume_agent.tailor import TailorError
from resume_agent.tracker import init_workbook
from resume_agent.triage import TRIAGE_MD, add_fit, triage_listing
from resume_agent.validation import resolve_listing

app = typer.Typer(help="Tailored Resume and Application Agent", no_args_is_help=True)
config_app = typer.Typer(help="Inspect the config file.", no_args_is_help=True)
app.add_typer(config_app, name="config")
dev_app = typer.Typer(help="Developer setup.", no_args_is_help=True)
app.add_typer(dev_app, name="dev")
HOOKS_PATH = ".githooks"


@app.callback()
def main() -> None:
    pass


def load_config_or_exit() -> Config:
    try:
        return load_config()
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


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
        workbook = init_workbook(config.data_root)
    except GuardError as error:
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

    triage = triage_listing(listing, config)
    ledger_path = baseline_dir(config, baseline or config.default_baseline) / LEDGER_FILE
    add_fit(triage, listing.text, ledger_path, lambda prompt: run_prompt(config, prompt))
    (out_dir / TRIAGE_MD).write_text(triage.markdown())
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
        result = tailor_folder(
            folder, config, lambda prompt: run_prompt(config, prompt), baseline, mode
        )
    except (
        BrowserError,
        DocumentError,
        FileNotFoundError,
        LedgerError,
        LlmError,
        PromptError,
        RenderError,
        TailorError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    typer.echo(f"Tailored ({result.mode.value}): {result.folder / DIFF_FILE}")
    for flag in result.flags:
        typer.echo(f"  Review: {flag}")
    typer.echo(f"ATS {'PASS' if result.render.passed else 'FAIL'}: {result.render.report}")
    if not result.render.passed:
        raise typer.Exit(1)


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
