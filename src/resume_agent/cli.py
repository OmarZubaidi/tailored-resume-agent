import subprocess
from pathlib import Path
from typing import Annotated

import typer

from resume_agent.browser import BrowserError
from resume_agent.config import Config, ConfigError, load_config
from resume_agent.data_root import dataless_paths, dataless_warning, init_data_root
from resume_agent.documents import DocumentError
from resume_agent.pipeline import baseline_dir, render_folder
from resume_agent.render import RenderError

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
    for path in created:
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
) -> None:
    """Render resume and cover letter PDFs and write the ATS report."""
    if folder and baseline:
        typer.echo("Pass a folder or --baseline, not both.", err=True)
        raise typer.Exit(1)
    config = load_config_or_exit()
    source = folder or baseline_dir(config, baseline or config.default_baseline)
    try:
        result = render_folder(source, config)
    except (BrowserError, DocumentError, RenderError, FileNotFoundError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    typer.echo(f"Wrote {result.resume_pdf}\nWrote {result.cover_letter_pdf}")
    typer.echo(f"ATS {'PASS' if result.passed else 'FAIL'}: {result.report}")
    if not result.passed:
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
