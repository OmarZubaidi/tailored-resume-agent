from datetime import date

import pytest
from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.stages import (
    Ambiguous,
    StageError,
    add_stage_event,
    find_application,
    load_variants,
    normalize,
    record_stage,
)
from resume_agent.tracker import (
    Application,
    Stage,
    Tracker,
    load_tracker,
    save_tracker,
    workbook_path,
)


def application(application_id: int, company: str, role: str, applied: date | None, **stages):
    dates = {Stage(name): day for name, day in stages.items()}
    if applied:
        dates[Stage.APPLIED] = applied
    return Application(
        id=application_id,
        company=company,
        role=role,
        stages=dates,
    )


@pytest.fixture
def tracker() -> Tracker:
    return Tracker(
        applications=[
            application(1, "Acme Health Inc.", "Backend Engineer", date(2026, 8, 1)),
            application(2, "Acme Health", "Frontend Engineer", date(2026, 11, 1)),
            application(3, "Globex", "Engineer", date(2026, 11, 2)),
            application(4, "Globex", "Platform Engineer", date(2026, 11, 3)),
            application(5, "Initech", "Engineer", date(2026, 10, 1), Rejected=date(2026, 10, 9)),
        ]
    )


def test_normalize_drops_case_punctuation_and_legal_suffixes():
    assert normalize("Anthropic, PBC") == "anthropic"
    assert normalize("ACME Health Inc.") == "acme health"


def test_single_open_application_matches(tracker):
    tracker.applications.pop(3)

    assert find_application(tracker, "GLOBEX", {}).id == 3


def test_closed_applications_are_ignored(tracker):
    with pytest.raises(StageError, match="No open application at Initech"):
        find_application(tracker, "Initech", {})


def test_newest_wins_when_sixty_days_newer(tracker):
    assert find_application(tracker, "Acme Health", {}).id == 2


def test_title_breaks_a_close_tie(tracker):
    assert find_application(tracker, "Globex", {}, title="platform engineer").id == 4
    assert find_application(tracker, "Globex", {}, title="Platform").id == 4
    assert find_application(tracker, "Globex", {}, title="Engineer").id == 3


def test_ambiguous_lists_candidates(tracker):
    with pytest.raises(Ambiguous) as raised:
        find_application(tracker, "Globex", {})

    assert [app.id for app in raised.value.candidates] == [3, 4]


def test_id_overrides_matching(tracker):
    assert find_application(tracker, "anything", {}, application_id=5).id == 5
    with pytest.raises(StageError, match="No application with ID 00099"):
        find_application(tracker, "anything", {}, application_id=99)


def test_variants_map_to_company(tmp_path, tracker):
    (tmp_path / "companies.yaml").write_text("Initech:\n  - Initrode\nGlobex:\n  - Globex Corp\n")
    tracker.applications.pop(3)

    assert find_application(tracker, "Globex Corporation", load_variants(tmp_path)).id == 3


def test_bad_variants_file(tmp_path):
    (tmp_path / "companies.yaml").write_text("Globex: Globex Corp\n")

    with pytest.raises(StageError, match="list of name variants"):
        load_variants(tmp_path)


def test_stage_event_writes_timeline(tmp_path):
    folder = tmp_path / "applications/00003 Globex - Engineer (2026-11-02)"
    folder.mkdir(parents=True)
    globex = application(3, "Globex", "Engineer", date(2026, 11, 2))
    globex.folder = folder.name

    record_stage(globex, Stage.SECOND, date(2026, 12, 10))
    add_stage_event(globex, Stage.SECOND, date(2026, 12, 10), tmp_path, "technical")

    assert globex.stages[Stage.SECOND] == date(2026, 12, 10)
    assert (folder / "timeline.md").read_text().endswith("- 2026-12-10 2nd: technical\n")


def test_recorded_stage_is_not_overwritten():
    globex = application(3, "Globex", "Engineer", date(2026, 11, 2))

    with pytest.raises(StageError, match="already has Applied 2026-11-02"):
        record_stage(globex, Stage.APPLIED, date(2026, 11, 20))

    assert globex.stages[Stage.APPLIED] == date(2026, 11, 2)


@pytest.fixture
def config(config_data, write_config, data_root, tracker) -> Config:
    data_root.mkdir(parents=True)
    write_config(config_data)
    config = Config(**config_data)
    save_tracker(tracker, config)
    return config


def test_update_command_saves_stage(config):
    result = CliRunner().invoke(app, ["update", "Acme Health", "rejected", "--date", "2026-11-20"])

    assert result.exit_code == 0, result.output
    saved = load_tracker(workbook_path(config.data_root))
    assert saved.applications[1].stages[Stage.REJECTED] == date(2026, 11, 20)


def test_update_command_prints_pick_list(config):
    result = CliRunner().invoke(app, ["update", "Globex", "1st"])

    assert result.exit_code == 1
    assert "00003  Globex - Engineer (applied 2026-11-02)" in result.output
    assert "Rerun with --id" in result.output
