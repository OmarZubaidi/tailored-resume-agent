import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.guards.precommit import blocked_by_name, data_root_markers, find_violations, run


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def stage(repo: Path, relative: str, content: str = "x") -> None:
    file = repo / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    subprocess.run(["git", "add", "-f", relative], cwd=repo, check=True)


@pytest.mark.parametrize(
    "path",
    [
        "resume.pdf",
        "a/Jane-Doe-Resume.PDF",
        "listing.md",
        "applications/00001/listing.pdf",
        "Job Applications.xlsx",
        "~$Job Applications.xlsx",
        "resume.docx",
        "config.yaml",
        "drafts/resume.md",
        "x/.state/progress.json",
    ],
)
def test_blocked_names(path):
    assert blocked_by_name(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/listing_fetch.py",
        "docs/research.md",
        "pdf_notes.txt",
        "docs/drafts.md",
        "config.example.yaml",
    ],
)
def test_allowed_names(path):
    assert not blocked_by_name(path)


def test_proton_account_path_blocked_without_config(repo, data_root):
    stage(repo, "notes.md", f"{data_root}\n")

    assert find_violations(repo, set()) == ["staged content contains the data_root path"]


def test_proton_glob_pattern_is_allowed(repo):
    stage(repo, "config.example.yaml", 'data_root: "~/CloudStorage/ProtonDrive-*/Data"\n')

    assert find_violations(repo, set()) == []


def test_clean_commit_passes(repo):
    stage(repo, "src/app.py", "print('hi')\n")

    assert find_violations(repo, {"/Data Root"}) == []


def test_blocks_pdf(repo):
    stage(repo, "resume.pdf")

    assert find_violations(repo, set()) == ["resume.pdf: data-like file type"]


def test_blocks_data_root_in_path(repo):
    stage(repo, "copy/Resume Agent Data/notes.md")

    violations = find_violations(repo, {"Resume Agent Data"})

    assert violations == ["copy/Resume Agent Data/notes.md: path contains data_root"]


def test_blocks_data_root_in_content(repo):
    stage(repo, "notes.md", 'root = "/Users/me/Resume Agent Data"\n')

    violations = find_violations(repo, {"/Users/me/Resume Agent Data"})

    assert violations == ["staged content contains the data_root path"]


def test_markers_include_tilde_form(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    data_root = tmp_path / "Data"

    assert data_root_markers(data_root) == {str(data_root), "~/Data"}


def test_run_uses_config_data_root(repo, config_data, write_config):
    write_config(
        {
            **config_data,
            "data_root": "/Volumes/Backup/Resume Agent Data",
        }
    )
    stage(repo, "notes.md", "/Volumes/Backup/Resume Agent Data\n")

    assert run(repo) == 1


def test_run_without_config_still_blocks_names(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("RESUME_AGENT_CONFIG", str(tmp_path / "missing.yaml"))
    stage(repo, "listing.pdf")

    assert run(repo) == 1


def test_install_hooks_sets_hooks_path(repo, monkeypatch):
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(app, ["dev", "install-hooks"])

    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result.exit_code == 0
    assert hooks_path == ".githooks"


def test_install_hooks_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    result = CliRunner().invoke(app, ["dev", "install-hooks"])

    assert result.exit_code == 1
    assert "Run this inside the repo" in result.output


def test_hook_script_is_executable():
    hook = Path(__file__).parent.parent / ".githooks" / "pre-commit"

    assert hook.stat().st_mode & 0o111
