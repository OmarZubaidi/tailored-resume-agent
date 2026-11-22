from typer.testing import CliRunner

from resume_agent.cli import app


def test_help_lists_app_name():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Tailored Resume and Application Agent" in result.output
