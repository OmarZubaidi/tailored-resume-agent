import typer

from resume_agent.config import ConfigError, load_config

app = typer.Typer(help="Tailored Resume and Application Agent", no_args_is_help=True)
config_app = typer.Typer(help="Inspect the config file.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@app.callback()
def main() -> None:
    pass


@config_app.command("check")
def config_check() -> None:
    """Validate the config file."""
    try:
        config = load_config()
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Config OK. data_root: {config.data_root}")
