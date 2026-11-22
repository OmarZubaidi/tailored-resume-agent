from browser_marks import needs_browser
from typer.testing import CliRunner

from resume_agent.cli import app

REQUIREMENTS = " ".join(f"Experience with system number {n}." for n in range(80))
PAGE = f"""<!doctype html>
<html><head><title>Careers</title></head>
<body><main>
  <h1>Senior Software Engineer</h1>
  <p>This role is onsite in Austin, TX.</p>
  <h2>Requirements</h2>
  <p>{REQUIREMENTS}</p>
</main></body></html>
"""


def test_fetch_requires_exactly_one_source(config_data, write_config, tmp_path):
    write_config(config_data)

    neither = CliRunner().invoke(app, ["fetch", str(tmp_path)])
    both = CliRunner().invoke(app, ["fetch", str(tmp_path), "--url", "x", "--pdf", "y.pdf"])

    assert neither.exit_code == both.exit_code == 1
    assert "exactly one of --url or --pdf" in neither.output


def test_fetch_missing_pdf(config_data, write_config, tmp_path):
    write_config(config_data)

    result = CliRunner().invoke(app, ["fetch", str(tmp_path / "out"), "--pdf", "missing.pdf"])

    assert result.exit_code == 1
    assert "missing.pdf" in result.output


@needs_browser
def test_fetch_url_writes_listing_and_triage(config_data, write_config, tmp_path):
    write_config(
        {
            **config_data,
            "location": "Springfield, IL",
        }
    )
    page = tmp_path / "job.html"
    page.write_text(PAGE)
    out = tmp_path / "out"

    result = CliRunner().invoke(app, ["fetch", str(out), "--url", page.as_uri()])

    assert result.exit_code == 0, result.output
    assert "Listing: Senior Software Engineer (" in result.output
    assert "Triage FLAGGED" in result.output
    assert (out / "listing.pdf").exists()
    assert (out / "listing.md").exists()
    assert "Springfield is not mentioned" in (out / "triage.md").read_text()
