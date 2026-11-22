import typer

from resume_agent.config import Config, ConfigError, load_config
from resume_agent.data_root import dataless_paths, dataless_warning, init_data_root

app = typer.Typer(help="Tailored Resume and Application Agent", no_args_is_help=True)
config_app = typer.Typer(help="Inspect the config file.", no_args_is_help=True)
app.add_typer(config_app, name="config")


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
