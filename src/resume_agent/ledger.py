from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from resume_agent.documents import DocumentError, parse_month

LEDGER_FILE = "skills-ledger.yaml"
MONTHS_PER_YEAR = 12


class LedgerError(Exception):
    pass


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def months(self) -> int:
        return (self.end.year - self.start.year) * 12 + self.end.month - self.start.month + 1


@dataclass
class Usage:
    periods: list[Period] = field(default_factory=list)
    extra_months: int = 0
    where: list[str] = field(default_factory=list)


@dataclass
class Ledger:
    roles: dict[str, Period]
    skills: dict[str, Usage]
    metrics: dict[str, str]

    def usage(self, skill: str) -> Usage | None:
        lowered = {name.lower(): usage for name, usage in self.skills.items()}
        return lowered.get(skill.lower())

    def skill_months(self, skill: str) -> int:
        usage = self.usage(skill)
        if usage is None:
            return 0
        return merged_months(usage.periods) + usage.extra_months

    def experience_months(self) -> int:
        return merged_months(list(self.roles.values()))


def merged_months(periods: list[Period]) -> int:
    total, current = 0, None
    for period in sorted(periods, key=lambda item: item.start):
        if current and period.start <= next_month(current.end):
            current = Period(current.start, max(current.end, period.end))
            continue
        if current:
            total += current.months
        current = period
    return total + (current.months if current else 0)


def next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def whole_years(months: int) -> int:
    return months // MONTHS_PER_YEAR


def parse_period(raw: dict, label: str, today: date) -> Period:
    if not isinstance(raw, dict):
        raise LedgerError(f"{label}: expected from: and to: on separate lines, got {raw!r}")
    try:
        period = Period(parse_month(raw["from"], today), parse_month(raw["to"], today))
    except KeyError as error:
        raise LedgerError(f"{label}: needs both from and to") from error
    except DocumentError as error:
        raise LedgerError(f"{label}: {error}") from error
    if period.start > period.end:
        raise LedgerError(f"{label}: ends before it starts")
    return period


def parse_usage(skill: str, entries: list, roles: dict[str, Period], today: date) -> Usage:
    usage = Usage()
    for index, entry in enumerate(entries or [], start=1):
        label = f"skills.{skill}[{index}]"
        if not isinstance(entry, dict):
            raise LedgerError(f"{label}: expected role:, from/to, or months:")
        if "role" in entry:
            if entry["role"] not in roles:
                raise LedgerError(f"{label}: unknown role {entry['role']!r}; add it under roles")
            usage.periods.append(roles[entry["role"]])
            usage.where.append(entry["role"])
        elif "months" in entry:
            if not isinstance(entry["months"], int) or entry["months"] <= 0:
                raise LedgerError(f"{label}: months must be a positive whole number")
            usage.extra_months += entry["months"]
            usage.where.extend(entry.get("where", []))
        elif "from" in entry or "to" in entry:
            usage.periods.append(parse_period(entry, label, today))
            usage.where.extend(entry.get("where", []))
        else:
            raise LedgerError(f"{label}: expected role:, from/to, or months:")
    return usage


def load_ledger(path: Path, today: date | None = None) -> Ledger:
    today = today or date.today()
    if not path.is_file():
        raise LedgerError(f"Skills ledger not found at {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as error:
        raise LedgerError(f"Skills ledger at {path} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise LedgerError(f"Skills ledger at {path} must have roles:, skills: and metrics:")

    roles = {
        name: parse_period(period, f"roles.{name}", today)
        for name, period in (raw.get("roles") or {}).items()
    }
    skills = {
        skill: parse_usage(skill, entries, roles, today)
        for skill, entries in (raw.get("skills") or {}).items()
    }
    metrics = {str(key): str(value) for key, value in (raw.get("metrics") or {}).items()}
    return Ledger(roles=roles, skills=skills, metrics=metrics)
