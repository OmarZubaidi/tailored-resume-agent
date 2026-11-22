import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from resume_agent.application_folder import add_timeline_event, application_dir, format_id
from resume_agent.config import Config
from resume_agent.tracker import (
    Application,
    Stage,
    Tracker,
    check_saveable,
    save_tracker,
    workbook_path,
)

COMPANIES_FILE = "companies.yaml"
LOCKING_STAGES = (Stage.APPLIED, Stage.REJECTED, Stage.SKIPPED)
CLEAR_LEAD = timedelta(days=60)
LEGAL_SUFFIXES = frozenset(
    {"inc", "llc", "ltd", "limited", "pbc", "corp", "corporation", "co", "company", "plc", "gmbh"}
)
NON_WORD = re.compile(r"[^a-z0-9]+")


class StageError(Exception):
    pass


@dataclass
class Ambiguous(Exception):
    candidates: list[Application]


def normalize(name: str) -> str:
    words = NON_WORD.sub(" ", name.lower()).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def load_variants(data_root: Path) -> dict[str, str]:
    path = data_root / COMPANIES_FILE
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict) or not all(
        isinstance(names, list) and all(isinstance(name, str) for name in names)
        for names in raw.values()
    ):
        raise StageError(f"{COMPANIES_FILE} must map each company to a list of name variants")
    lookup = {}
    for company, names in raw.items():
        for name in [company, *names]:
            lookup[normalize(name)] = normalize(company)
    return lookup


def company_key(name: str, variants: dict[str, str]) -> str:
    key = normalize(name)
    return variants.get(key, key)


def applied_on(application: Application) -> date | None:
    return application.stages.get(Stage.APPLIED)


def clear_newest(candidates: list[Application]) -> Application | None:
    dated = sorted((app for app in candidates if applied_on(app)), key=applied_on, reverse=True)
    if len(dated) != len(candidates):
        return None
    newest, runner_up = dated[0], dated[1]
    return newest if applied_on(newest) - applied_on(runner_up) >= CLEAR_LEAD else None


def by_title(candidates: list[Application], title: str) -> list[Application]:
    wanted = normalize(title)
    if not wanted:
        return []
    tiers = (
        lambda role: role == wanted,
        lambda role: wanted in role,
        lambda role: role in wanted,
    )
    for matches in tiers:
        found = [app for app in candidates if matches(normalize(app.role))]
        if found:
            return found
    return []


def find_application(
    tracker: Tracker,
    company: str,
    variants: dict[str, str],
    title: str | None = None,
    application_id: int | None = None,
) -> Application:
    if application_id is not None:
        match = next((app for app in tracker.applications if app.id == application_id), None)
        if match is None:
            raise StageError(f"No application with ID {format_id(application_id)}")
        return match

    key = company_key(company, variants)
    candidates = [
        app
        for app in tracker.applications
        if app.is_open and company_key(app.company, variants) == key
    ]
    if not candidates:
        raise StageError(f"No open application at {company}")
    if len(candidates) == 1:
        return candidates[0]
    newest = clear_newest(candidates)
    if newest:
        return newest
    titled = by_title(candidates, title) if title else []
    if len(titled) == 1:
        return titled[0]
    raise Ambiguous(titled or candidates)


def pick_line(application: Application) -> str:
    applied = applied_on(application)
    started = f"applied {applied}" if applied else application.status.lower()
    return f"{format_id(application.id)}  {application.company} - {application.role} ({started})"


def record_stage(application: Application, stage: Stage, day: date) -> None:
    if stage in application.stages:
        raise StageError(
            f"{pick_line(application)} already has {stage.value} "
            f"{application.stages[stage]}. Change the cell in Excel if it is wrong."
        )
    application.stages[stage] = day


def add_stage_event(
    application: Application,
    stage: Stage,
    day: date,
    data_root: Path,
    note: str | None = None,
) -> None:
    folder = application_dir(data_root, application)
    if folder:
        add_timeline_event(folder, day, f"{stage.value}: {note}" if note else stage.value)


def save_stage[T](
    tracker: Tracker,
    application: Application,
    stage: Stage,
    day: date,
    config: Config,
    note: str | None = None,
    before_save: Callable[[], T] | None = None,
) -> T | None:
    record_stage(application, stage, day)
    check_saveable(tracker, workbook_path(config.data_root))
    prepared = before_save() if before_save else None
    save_tracker(tracker, config)
    add_stage_event(application, stage, day, config.data_root, note)
    return prepared
