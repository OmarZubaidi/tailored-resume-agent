from datetime import date
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from resume_agent.config import Config
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
    with_ignored_errors,
    workbook_path,
)

TODAY = date(2026, 11, 21)


@pytest.fixture
def config(config_data, data_root) -> Config:
    (data_root / "baselines/general").mkdir(parents=True)
    return Config(**config_data)


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
def saved(config, acme) -> Tracker:
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
    save_tracker(tracker, config, TODAY)
    return tracker


@pytest.fixture
def path(config) -> object:
    return workbook_path(config.data_root)


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


def test_round_trip(path, saved):
    assert load_tracker(path) == saved


def test_sheets_and_formulas(path, saved):
    workbook = load_workbook(path)

    assert workbook.sheetnames == [INBOX_SHEET, APPLICATIONS_SHEET, OVERVIEW_SHEET]
    applications = workbook[APPLICATIONS_SHEET]
    assert applications["A2"].value == 42
    assert applications["A2"].number_format == "00000"
    assert applications["D2"].value == status_formula(2)
    folder = saved.applications[0].folder
    assert applications["O2"].hyperlink.target == f"applications/{folder}"
    assert applications["O2"].value == 42
    assert applications["O2"].number_format == "00000"
    assert applications.column_dimensions["O"].width == applications.column_dimensions["A"].width
    assert {sheet.sheet_view.zoomScale for sheet in workbook.worksheets} == {150}
    overview = workbook[OVERVIEW_SHEET]
    assert overview["A2"].value == "Total"
    applied, first, rejected = (
        f"Applications!${column}$2:${column}$1048576" for column in ("E", "F", "J")
    )
    assert overview["B2"].value == f'=COUNTIFS({applied},"<>")'
    assert overview["A3"].value.date() == date(2026, 11, 16)
    in_week = f'{applied},">="&$A3,{applied},"<"&$A3+7'
    assert overview["C3"].value == f'=COUNTIFS({in_week},{first},"<>")'
    assert overview["L3"].value == f'=COUNTIFS({in_week},{first},"",{rejected},"")'


def test_listing_text_is_never_written_as_a_formula(config):
    hostile = Application(
        id=1,
        company='=HYPERLINK("https://evil.example","Acme")',
        role="=1+1",
    )

    save_tracker(Tracker(applications=[hostile]), config, TODAY)

    applications = load_workbook(workbook_path(config.data_root))[APPLICATIONS_SHEET]
    assert applications["B2"].data_type == "s"
    assert applications["C2"].data_type == "s"
    assert applications["D2"].data_type == "f"


def test_cells_use_template_styles(path, saved):
    workbook = load_workbook(path)
    applications = workbook[APPLICATIONS_SHEET]
    inbox = workbook[INBOX_SHEET]

    assert applications["A1"].style == "Heading"
    assert applications["A2"].style == "Normal"
    assert applications["B2"].font.b
    assert applications["E2"].style == "Input"
    assert applications["N2"].style == "Hyperlink"
    assert inbox["A3"].style == "Input"
    assert not workbook.template
    assert "Currency: USD" not in workbook.named_styles
    assert applications.column_dimensions["E"].width == 12


def test_formula_warnings_are_ignored_on_every_sheet(path, saved):
    with ZipFile(path) as package:
        sheets = [name for name in package.namelist() if name.startswith("xl/worksheets/sheet")]
        assert len(sheets) == 3
        for name in sheets:
            assert 'formula="1"' in package.read(name).decode()


def test_ignored_errors_go_before_later_elements():
    xml = "<worksheet><sheetData/><pageMargins/><tableParts/></worksheet>"

    assert with_ignored_errors(xml).index("<ignoredErrors>") == xml.index("<tableParts")


def test_inbox_offers_mode_and_baseline_choices(path, saved):
    inbox = load_workbook(path)[INBOX_SHEET]

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


def test_save_refuses_while_open_in_excel(config, path):
    excel_lock_file(path).write_text("")

    with pytest.raises(GuardError, match="open in Excel"):
        save_tracker(Tracker(), config, TODAY)


def test_missing_template(config_data, data_root, tmp_path):
    config = Config(**{**config_data, "excel_template": str(tmp_path / "missing.xltx")})

    with pytest.raises(TrackerError, match="Excel template not found"):
        save_tracker(Tracker(), config, TODAY)


def test_template_without_styles(config_data, data_root, tmp_path):
    data_root.mkdir(parents=True)
    template = tmp_path / "Plain.xltx"
    workbook = Workbook()
    workbook.template = True
    workbook.save(template)
    config = Config(**{**config_data, "excel_template": str(template)})

    with pytest.raises(TrackerError, match="no cell styles named: Heading, Input"):
        save_tracker(Tracker(), config, TODAY)


def test_folder_is_read_from_an_encoded_link(path, saved):
    workbook = load_workbook(path)
    workbook[APPLICATIONS_SHEET]["O2"].hyperlink = "applications/00042%20Acme%20Health"
    workbook.save(path)

    assert load_tracker(path).applications[0].folder == "00042 Acme Health"


def test_bad_date_names_the_cell(path, saved):
    workbook = load_workbook(path)
    workbook[APPLICATIONS_SHEET]["F2"] = "next week"
    workbook.save(path)

    with pytest.raises(TrackerError, match="Applications row 2 1st: 'next week'"):
        load_tracker(path)


def test_changed_columns_are_rejected(path, saved):
    workbook = load_workbook(path)
    workbook[APPLICATIONS_SHEET]["B1"] = "Employer"
    workbook.save(path)

    with pytest.raises(TrackerError, match="Applications sheet columns changed"):
        load_tracker(path)


def test_init_workbook_does_not_overwrite(config, path):
    assert init_workbook(config, TODAY) == path
    assert init_workbook(config, TODAY) is None
    assert load_tracker(path) == Tracker()
