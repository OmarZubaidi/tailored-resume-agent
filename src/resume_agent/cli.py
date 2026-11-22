import typer

app = typer.Typer(help="Tailored Resume and Application Agent", no_args_is_help=True)


@app.callback()
def main() -> None:
    pass
