from datetime import date

import pytest
from openpyxl import load_workbook

from resume_agent.guards.rules import GuardError, excel_lock_file
from resume_agent.tracker import (
    APPLICATIONS_SHEET,
    INBOX_SHEET,
    OVERVIEW_SHEET,
    Application,
    InboxRow,
    Stage,
    Tracker,
    TrackerError,
    init_workbook,
    load_tracker,
    overview_weeks,
    save_tracker,
    status_formula,
    workbook_path,
)

TODAY = date(2026, 11, 21)


@pytest.fixture
def acme() -> Application:
    return Application(
        id=42,
        company="Acme Health",
        role="Software Engineer",
        link="https://jobs.example.com/acme/1",
        folder="00042 Acme Health - Software Engineer (2026-11-16)",
        mode="upward",
        baseline="general",
        notes="referral",
        stages={
            Stage.APPLIED: date(2026, 11, 16),
            Stage.FIRST: date(2026, 11, 19),
        },
    )


@pytest.fixture
def saved(tmp_path, acme) -> Tracker:
    tracker = Tracker(
        applications=[acme],
        inbox=[
            InboxRow(
                url="https://jobs.example.com/globex/7",
                mode="lateral",
                status="flagged",
                id=43,
                folder="00043 Globex - Engineer (2026-11-21)",
                reason="clearance required",
            )
        ],
    )
    (tmp_path / "baselines/general").mkdir(parents=True)
    save_tracker(tracker, workbook_path(tmp_path), tmp_path, TODAY)
    return tracker


def test_status_follows_precedence(acme):
    assert acme.status == "1st"
    acme.stages[Stage.REJECTED] = date(2026, 11, 20)
    assert acme.status == "Rejected"
    assert not acme.is_open


def test_status_without_stages_is_interested():
    application = Application(
        id=1,
        company="Globex",
        role="Engineer",
    )

    assert application.status == "Interested"
    assert application.is_open


def test_status_formula_checks_skipped_first_and_falls_back_to_interested():
    formula = status_formula(2)

    assert formula.startswith('=IF(K2<>"","Skipped",IF(J2<>"","Rejected"')
    assert formula.endswith('IF(E2<>"","Applied","Interested")))))))')


def test_round_trip(tmp_path, saved):
    assert load_tracker(workbook_path(tmp_path)) == saved


def test_sheets_and_formulas(tmp_path, saved):
    workbook = load_workbook(workbook_path(tmp_path))

    assert workbook.sheetnames == [INBOX_SHEET, APPLICATIONS_SHEET, OVERVIEW_SHEET]
    applications = workbook[APPLICATIONS_SHEET]
    assert applications["A2"].value == 42
    assert applications["A2"].number_format == "00000"
    assert applications["D2"].value == status_formula(2)
    folder = saved.applications[0].folder
    assert applications["O2"].hyperlink.target == f"applications/{folder}"
    assert {sheet.sheet_view.zoomScale for sheet in workbook.worksheets} == {150}
    overview = workbook[OVERVIEW_SHEET]
    assert overview["A2"].value == "Total"
    assert overview["B2"].value == '=COUNTIFS(Applications!$E:$E,"<>")'
    assert overview["A3"].value.date() == date(2026, 11, 16)
    assert overview["C3"].value == (
        '=COUNTIFS(Applications!$E:$E,">="&$A3,Applications!$E:$E,"<"&$A3+7,'
        'Applications!$F:$F,"<>")'
    )
    assert overview["L3"].value == (
        '=COUNTIFS(Applications!$E:$E,">="&$A3,Applications!$E:$E,"<"&$A3+7,'
        'Applications!$F:$F,"",Applications!$J:$J,"")'
    )


def test_headers_are_accented_and_input_cells_shaded(tmp_path, saved):
    workbook = load_workbook(workbook_path(tmp_path))
    applications = workbook[APPLICATIONS_SHEET]
    inbox = workbook[INBOX_SHEET]

    assert applications["A1"].font.color.rgb == "FFED217C"
    assert applications["E2"].fill.fgColor.rgb == "FFCCCCCC"
    assert applications["B2"].fill.fgColor.rgb != "FFCCCCCC"
    assert inbox["A3"].fill.fgColor.rgb == "FFCCCCCC"


def test_inbox_offers_mode_and_baseline_choices(tmp_path, saved):
    inbox = load_workbook(workbook_path(tmp_path))[INBOX_SHEET]

    choices = {validation.formula1 for validation in inbox.data_validations.dataValidation}
    assert choices == {'"upward,lateral"', '"general"'}


def test_overview_weeks_run_newest_first_from_first_applied_week(acme):
    acme.stages[Stage.APPLIED] = date(2026, 11, 4)

    assert overview_weeks([acme], TODAY) == [
        date(2026, 11, 16),
        date(2026, 11, 9),
        date(2026, 11, 2),
    ]


def test_overview_weeks_without_applications_is_current_week():
    assert overview_weeks([], TODAY) == [date(2026, 11, 16)]


def test_save_refuses_while_open_in_excel(tmp_path):
    path = workbook_path(tmp_path)
    excel_lock_file(path).write_text("")

    with pytest.raises(GuardError, match="open in Excel"):
        save_tracker(Tracker(), path, tmp_path, TODAY)


def test_bad_date_names_the_cell(tmp_path, saved):
    path = workbook_path(tmp_path)
    workbook = load_workbook(path)
    workbook[APPLICATIONS_SHEET]["F2"] = "next week"
    workbook.save(path)

    with pytest.raises(TrackerError, match="Applications row 2 1st: 'next week'"):
        load_tracker(path)


def test_changed_columns_are_rejected(tmp_path, saved):
    path = workbook_path(tmp_path)
    workbook = load_workbook(path)
    workbook[APPLICATIONS_SHEET]["B1"] = "Employer"
    workbook.save(path)

    with pytest.raises(TrackerError, match="Applications sheet columns changed"):
        load_tracker(path)


def test_init_workbook_does_not_overwrite(tmp_path):
    assert init_workbook(tmp_path, TODAY) == workbook_path(tmp_path)
    assert init_workbook(tmp_path, TODAY) is None
    assert load_tracker(workbook_path(tmp_path)) == Tracker()
