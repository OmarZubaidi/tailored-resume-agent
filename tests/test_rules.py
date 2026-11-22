import hashlib
from datetime import date

import pytest

from resume_agent.config import Config, Provider
from resume_agent.guards.rules import (
    GuardError,
    ensure_excel_closed,
    is_locked,
    lock_applied_files,
    require_apply_allowed,
    writable_target,
)


@pytest.fixture
def config(config_data) -> Config:
    return Config(**config_data)


def test_providers_cannot_read_files_or_bill_per_use():
    assert {provider.value for provider in Provider} == {
        "claude-code",
        "ollama",
        "lmstudio",
    }


def test_apply_blocked_by_default(config):
    with pytest.raises(GuardError, match="apply_on_my_behalf is false"):
        require_apply_allowed(config)


def test_apply_allowed_when_enabled(config):
    require_apply_allowed(config.model_copy(update={"apply_on_my_behalf": True}))


def test_excel_open_blocks_write(tmp_path):
    workbook = tmp_path / "Job Applications.xlsx"
    (tmp_path / "~$Job Applications.xlsx").write_text("")

    with pytest.raises(GuardError, match="open in Excel"):
        ensure_excel_closed(workbook)


def test_excel_closed_allows_write(tmp_path):
    ensure_excel_closed(tmp_path / "Job Applications.xlsx")


def test_lock_sets_read_only_and_records_hash(tmp_path):
    resume = tmp_path / "Jane-Doe-Resume.pdf"
    resume.write_bytes(b"pdf bytes")

    lock_applied_files(tmp_path, [resume.name], today=date(2026, 11, 21))

    digest = hashlib.sha256(b"pdf bytes").hexdigest()
    assert is_locked(resume)
    assert (tmp_path / "notes.md").read_text() == (
        f"- 2026-11-21 locked `{resume.name}` sha256 `{digest}`\n"
    )


def test_lock_twice_records_once(tmp_path):
    (tmp_path / "resume.md").write_text("x")

    lock_applied_files(tmp_path, ["resume.md"])
    lock_applied_files(tmp_path, ["resume.md"])

    assert len((tmp_path / "notes.md").read_text().splitlines()) == 1


def test_lock_with_missing_file_locks_nothing(tmp_path):
    resume = tmp_path / "resume.md"
    resume.write_text("x")

    with pytest.raises(GuardError, match="missing in .*: resume.pdf"):
        lock_applied_files(tmp_path, ["resume.md", "resume.pdf"])

    assert not is_locked(resume)
    assert not (tmp_path / "notes.md").exists()


def test_regeneration_after_lock_goes_to_drafts(tmp_path):
    (tmp_path / "resume.md").write_text("x")
    assert writable_target(tmp_path, "resume.md") == tmp_path / "resume.md"

    lock_applied_files(tmp_path, ["resume.md"])

    assert writable_target(tmp_path, "resume.md") == tmp_path / "drafts" / "resume.md"
    assert (tmp_path / "drafts").is_dir()
