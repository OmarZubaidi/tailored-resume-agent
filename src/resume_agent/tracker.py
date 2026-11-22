import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from resume_agent.data_root import APPLICATIONS_DIR, BASELINES_DIR
from resume_agent.guards.rules import ensure_excel_closed

WORKBOOK_FILE = "Job Applications.xlsx"
INBOX_SHEET = "Inbox"
APPLICATIONS_SHEET = "Applications"
OVERVIEW_SHEET = "Overview"
DATE_FORMAT = "mm-dd-yy"
ID_DIGITS = 5
ID_FORMAT = "0" * ID_DIGITS
PERCENT_FORMAT = "0%"
INTERESTED = "Interested"
MODES = ("upward", "lateral")
BLANK_INBOX_ROWS = 20
ZOOM_PERCENT = 150

FONT_NAME = "Calibri"
FONT_SIZE = 8
ACCENT = "FFED217C"
BODY_FONT = Font(name=FONT_NAME, sz=FONT_SIZE)
BOLD_FONT = Font(name=FONT_NAME, sz=FONT_SIZE, b=True)
HEADER_FONT = Font(name=FONT_NAME, sz=FONT_SIZE, b=True, color=ACCENT)
LINK_FONT = Font(name=FONT_NAME, sz=FONT_SIZE, u="single", color=ACCENT)
INPUT_FILL = PatternFill("solid", fgColor="FFCCCCCC")
RULE = Border(bottom=Side(style="thin", color="FF000000"))
BODY_ALIGNMENT = Alignment(vertical="center")
HEADER_ALIGNMENT = Alignment(horizontal="left", vertical="center")


class TrackerError(Exception):
    pass


class Stage(StrEnum):
    APPLIED = "Applied"
    FIRST = "1st"
    SECOND = "2nd"
    THIRD = "3rd"
    OFFER = "Offer"
    REJECTED = "Rejected"
    SKIPPED = "Skipped"


STATUS_PRECEDENCE = (
    Stage.SKIPPED,
    Stage.REJECTED,
    Stage.OFFER,
    Stage.THIRD,
    Stage.SECOND,
    Stage.FIRST,
    Stage.APPLIED,
)
CLOSED_STAGES = (Stage.REJECTED, Stage.SKIPPED)
STAGE_COLUMNS = frozenset(stage.value for stage in Stage)


@dataclass(frozen=True)
class Layout:
    columns: tuple[str, ...]
    widths: dict[str, float]
    inputs: frozenset[str] = frozenset()
    bold: frozenset[str] = frozenset()

    def letter(self, name: str) -> str:
        return get_column_letter(self.columns.index(name) + 1)


APPLICATIONS = Layout(
    columns=(
        "ID",
        "Company",
        "Role",
        "Status",
        *(stage.value for stage in Stage),
        "Mode",
        "Baseline",
        "Link",
        "Folder",
        "Notes",
    ),
    widths={
        "ID": 6,
        "Company": 20,
        "Role": 28,
        "Status": 9,
        **dict.fromkeys(STAGE_COLUMNS, 8),
        "Mode": 7,
        "Baseline": 9,
        "Link": 28,
        "Folder": 32,
        "Notes": 40,
    },
    inputs=STAGE_COLUMNS | {"Notes"},
    bold=frozenset({"Company"}),
)
INBOX = Layout(
    columns=("URL", "Mode", "Baseline", "Status", "ID", "Folder", "Reason"),
    widths={
        "URL": 50,
        "Mode": 8,
        "Baseline": 10,
        "Status": 9,
        "ID": 6,
        "Folder": 32,
        "Reason": 50,
    },
    inputs=frozenset({"URL", "Mode", "Baseline"}),
)
OVERVIEW = Layout(
    columns=(
        "Week Starting",
        "Apps",
        "1st #",
        "1st %",
        "2nd #",
        "2nd %",
        "3rd #",
        "3rd %",
        "Offers #",
        "Rejections #",
        "Rejections %",
        "No Answer #",
    ),
    widths={
        "Week Starting": 12,
        "Rejections #": 11,
        "Rejections %": 11,
        "No Answer #": 11,
    },
    bold=frozenset({"Week Starting"}),
)
DEFAULT_WIDTH = 8


@dataclass
class Application:
    id: int
    company: str
    role: str
    link: str = ""
    folder: str = ""
    mode: str = ""
    baseline: str = ""
    notes: str = ""
    stages: dict[Stage, date] = field(default_factory=dict)

    @property
    def status(self) -> str:
        filled = (stage.value for stage in STATUS_PRECEDENCE if stage in self.stages)
        return next(filled, INTERESTED)

    @property
    def is_open(self) -> bool:
        return not any(stage in self.stages for stage in CLOSED_STAGES)


@dataclass
class InboxRow:
    url: str
    mode: str = ""
    baseline: str = ""
    status: str = ""
    id: int | None = None
    folder: str = ""
    reason: str = ""


@dataclass
class Tracker:
    applications: list[Application] = field(default_factory=list)
    inbox: list[InboxRow] = field(default_factory=list)


def status_formula(row: int) -> str:
    formula = f'"{INTERESTED}"'
    for stage in reversed(STATUS_PRECEDENCE):
        cell = f"{APPLICATIONS.letter(stage.value)}{row}"
        formula = f'IF({cell}<>"","{stage.value}",{formula})'
    return f"={formula}"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def overview_weeks(applications: list[Application], today: date) -> list[date]:
    applied = [app.stages[Stage.APPLIED] for app in applications if Stage.APPLIED in app.stages]
    first = week_start(min(applied, default=today))
    current = week_start(max([today, *applied]))
    weeks = []
    while current >= first:
        weeks.append(current)
        current -= timedelta(days=7)
    return weeks


def stage_range(stage: Stage) -> str:
    letter = APPLICATIONS.letter(stage.value)
    return f"{APPLICATIONS_SHEET}!${letter}:${letter}"


def overview_formulas(row: int, week: str | None) -> list[str]:
    applied = stage_range(Stage.APPLIED)
    in_week = f'{applied},">="&{week},{applied},"<"&{week}+7' if week else f'{applied},"<>"'

    def count(*stages: Stage, empty: tuple[Stage, ...] = ()) -> str:
        filled = "".join(f',{stage_range(stage)},"<>"' for stage in stages)
        blank = "".join(f',{stage_range(stage)},""' for stage in empty)
        return f"=COUNTIFS({in_week}{filled}{blank})"

    def share(numerator: str, denominator: str) -> str:
        return f"=IFERROR({numerator}{row}/{denominator}{row},0)"

    return [
        count(),
        count(Stage.FIRST),
        share("C", "B"),
        count(Stage.SECOND),
        share("E", "C"),
        count(Stage.THIRD),
        share("G", "E"),
        count(Stage.OFFER),
        count(Stage.REJECTED),
        share("J", "B"),
        count(empty=(Stage.FIRST, Stage.REJECTED)),
    ]


def write_header(sheet: Worksheet, layout: Layout) -> None:
    for index, name in enumerate(layout.columns, start=1):
        cell = sheet.cell(row=1, column=index, value=name)
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT
        cell.border = RULE
        width = layout.widths.get(name, DEFAULT_WIDTH)
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"


def set_cell(sheet: Worksheet, row: int, layout: Layout, name: str, value=None):
    cell = sheet.cell(row=row, column=layout.columns.index(name) + 1, value=value or None)
    cell.font = BOLD_FONT if name in layout.bold else BODY_FONT
    cell.alignment = BODY_ALIGNMENT
    if name in layout.inputs:
        cell.fill = INPUT_FILL
    if isinstance(value, date) or name in STAGE_COLUMNS:
        cell.number_format = DATE_FORMAT
    elif name == "ID":
        cell.number_format = ID_FORMAT
    elif name.endswith("%"):
        cell.number_format = PERCENT_FORMAT
    return cell


def link_cell(sheet: Worksheet, row: int, layout: Layout, name: str, target: str) -> None:
    if not target:
        return
    cell = sheet.cell(row=row, column=layout.columns.index(name) + 1)
    cell.hyperlink = target
    cell.font = LINK_FONT


def folder_link(folder: str) -> str:
    return f"{APPLICATIONS_DIR}/{folder}" if folder else ""


def write_applications(sheet: Worksheet, applications: list[Application]) -> None:
    write_header(sheet, APPLICATIONS)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(APPLICATIONS.columns))}1"
    for row, app in enumerate(sorted(applications, key=lambda item: item.id), start=2):
        values = {
            "ID": app.id,
            "Company": app.company,
            "Role": app.role,
            "Status": status_formula(row),
            "Mode": app.mode,
            "Baseline": app.baseline,
            "Link": app.link,
            "Folder": app.folder,
            "Notes": app.notes,
            **{stage.value: app.stages.get(stage) for stage in Stage},
        }
        for name, value in values.items():
            set_cell(sheet, row, APPLICATIONS, name, value)
        link_cell(sheet, row, APPLICATIONS, "Link", app.link)
        link_cell(sheet, row, APPLICATIONS, "Folder", folder_link(app.folder))


def write_inbox(sheet: Worksheet, rows: list[InboxRow], baselines: list[str]) -> None:
    write_header(sheet, INBOX)
    for row, item in enumerate(rows, start=2):
        values = {
            "URL": item.url,
            "Mode": item.mode,
            "Baseline": item.baseline,
            "Status": item.status,
            "ID": item.id,
            "Folder": item.folder,
            "Reason": item.reason,
        }
        for name, value in values.items():
            set_cell(sheet, row, INBOX, name, value)
        link_cell(sheet, row, INBOX, "Folder", folder_link(item.folder))

    first_blank = len(rows) + 2
    for row in range(first_blank, first_blank + BLANK_INBOX_ROWS):
        for name in INBOX.columns:
            set_cell(sheet, row, INBOX, name)

    for name, choices in (("Mode", MODES), ("Baseline", baselines)):
        if not choices:
            continue
        letter = INBOX.letter(name)
        validation = DataValidation(type="list", formula1=f'"{",".join(choices)}"')
        validation.add(f"{letter}2:{letter}1048576")
        sheet.add_data_validation(validation)


def write_overview(sheet: Worksheet, applications: list[Application], today: date) -> None:
    write_header(sheet, OVERVIEW)
    labels: list[str | date] = ["Total", *overview_weeks(applications, today)]
    for row, label in enumerate(labels, start=2):
        week_cell = f"$A{row}" if isinstance(label, date) else None
        cells = [set_cell(sheet, row, OVERVIEW, OVERVIEW.columns[0], label)]
        formulas = overview_formulas(row, week_cell)
        for name, formula in zip(OVERVIEW.columns[1:], formulas, strict=True):
            cells.append(set_cell(sheet, row, OVERVIEW, name, formula))
        if week_cell is None:
            for cell in cells:
                cell.font = BOLD_FONT
                cell.border = RULE
    sheet.freeze_panes = "A3"


def baseline_names(data_root: Path) -> list[str]:
    baselines = data_root / BASELINES_DIR
    if not baselines.is_dir():
        return []
    return sorted(path.name for path in baselines.iterdir() if path.is_dir())


def save_tracker(tracker: Tracker, path: Path, data_root: Path, today: date | None = None):
    ensure_excel_closed(path)
    workbook = Workbook()
    inbox = workbook.active
    inbox.title = INBOX_SHEET
    write_inbox(inbox, tracker.inbox, baseline_names(data_root))
    write_applications(workbook.create_sheet(APPLICATIONS_SHEET), tracker.applications)
    overview = workbook.create_sheet(OVERVIEW_SHEET)
    write_overview(overview, tracker.applications, today or date.today())
    for sheet in workbook.worksheets:
        sheet.sheet_view.zoomScale = ZOOM_PERCENT
    workbook.calculation.fullCalcOnLoad = True

    partial = path.with_name(f".{path.name}.partial")
    workbook.save(partial)
    os.replace(partial, path)


def cell_text(value) -> str:
    return "" if value is None else str(value).strip()


def cell_date(value, where: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as error:
        raise TrackerError(f"{where}: {value!r} is not a date (use YYYY-MM-DD)") from error


def cell_id(value, where: str) -> int | None:
    text = cell_text(value)
    if not text:
        return None
    if not text.isdigit():
        raise TrackerError(f"{where}: ID {text!r} is not a number")
    return int(text)


def sheet_rows(workbook, name: str, layout: Layout) -> list[tuple[int, dict]]:
    if name not in workbook.sheetnames:
        raise TrackerError(f"Workbook has no {name!r} sheet. Was it made by `resume_agent init`?")
    sheet = workbook[name]
    header = tuple(cell_text(cell.value) for cell in sheet[1])[: len(layout.columns)]
    if header != layout.columns:
        raise TrackerError(f"{name} sheet columns changed. Expected: {', '.join(layout.columns)}")
    rows = []
    for number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        record = dict(zip(layout.columns, values, strict=False))
        if any(cell_text(value) for value in record.values()):
            rows.append((number, record))
    return rows


def read_application(number: int, record: dict) -> Application:
    where = f"{APPLICATIONS_SHEET} row {number}"
    application_id = cell_id(record["ID"], where)
    if application_id is None:
        raise TrackerError(f"{where}: missing ID")
    stages = {}
    for stage in Stage:
        day = cell_date(record[stage.value], f"{where} {stage.value}")
        if day:
            stages[stage] = day
    return Application(
        id=application_id,
        company=cell_text(record["Company"]),
        role=cell_text(record["Role"]),
        link=cell_text(record["Link"]),
        folder=cell_text(record["Folder"]),
        mode=cell_text(record["Mode"]),
        baseline=cell_text(record["Baseline"]),
        notes=cell_text(record["Notes"]),
        stages=stages,
    )


def read_inbox_row(number: int, record: dict) -> InboxRow:
    return InboxRow(
        url=cell_text(record["URL"]),
        mode=cell_text(record["Mode"]).lower(),
        baseline=cell_text(record["Baseline"]),
        status=cell_text(record["Status"]).lower(),
        id=cell_id(record["ID"], f"{INBOX_SHEET} row {number}"),
        folder=cell_text(record["Folder"]),
        reason=cell_text(record["Reason"]),
    )


def load_tracker(path: Path) -> Tracker:
    if not path.is_file():
        raise TrackerError(f"No workbook at {path}. Run `resume_agent init`.")
    workbook = load_workbook(path)
    return Tracker(
        applications=[
            read_application(number, record)
            for number, record in sheet_rows(workbook, APPLICATIONS_SHEET, APPLICATIONS)
        ],
        inbox=[
            read_inbox_row(number, record)
            for number, record in sheet_rows(workbook, INBOX_SHEET, INBOX)
        ],
    )


def workbook_path(data_root: Path) -> Path:
    return data_root / WORKBOOK_FILE


def init_workbook(data_root: Path, today: date | None = None) -> Path | None:
    path = workbook_path(data_root)
    if path.exists():
        return None
    save_tracker(Tracker(), path, data_root, today)
    return path
