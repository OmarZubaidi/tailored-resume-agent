import subprocess

import typer

from resume_agent.config import Config, ConfigError, load_config
from resume_agent.data_root import dataless_paths, dataless_warning, init_data_root

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
