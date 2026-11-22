import re
from dataclasses import dataclass, field
from datetime import date

import yaml

FRONT_MATTER_DELIMITER = "---"
MONTH_YEAR = r"(0[1-9]|1[0-2])/(\d{4})"
DATE_RANGE = re.compile(rf"\b{MONTH_YEAR} - (?:{MONTH_YEAR}|present)\b")
ANY_MONTH_YEAR = re.compile(r"\b\d{1,2}/\d{4}\b")
FORBIDDEN_DASHES = ("–", "—")


class DocumentError(Exception):
    pass


@dataclass
class Role:
    title: str
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    roles: list[Role] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class Resume:
    headline: str
    sections: list[Section]

    def text_lines(self) -> list[str]:
        lines = [self.headline]
        for section in self.sections:
            lines.append(section.title)
            for role in section.roles:
                lines.extend([role.title, role.subtitle, *role.bullets])
            lines.extend(section.items)
            lines.extend(section.paragraphs)
        return [line for line in lines if line]


def split_front_matter(text: str) -> tuple[dict, list[str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        return {}, lines
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONT_MATTER_DELIMITER
        )
    except StopIteration as error:
        raise DocumentError("Front matter starts with --- but never closes") from error
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as error:
        raise DocumentError(f"Front matter is not valid YAML: {error}") from error
    if not isinstance(meta, dict):
        raise DocumentError("Front matter must be key: value pairs")
    return meta, lines[end + 1 :]


def parse_resume(text: str) -> Resume:
    meta, lines = split_front_matter(text)
    headline = str(meta.get("headline", "")).strip()
    sections: list[Section] = []
    role: Role | None = None

    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("## "):
            sections.append(Section(title=line[3:].strip()))
            role = None
            continue
        if not sections:
            raise DocumentError(f"Line {number}: content before the first ## section: {line!r}")

        section = sections[-1]
        if line.startswith("### "):
            role = Role(title=line[4:].strip())
            section.roles.append(role)
        elif line.startswith("- "):
            (role.bullets if role else section.items).append(line[2:].strip())
        elif role and not role.subtitle and not role.bullets:
            role.subtitle = line
        else:
            section.paragraphs.append(line)
            role = None

    return Resume(headline=headline, sections=sections)


def date_problems(lines: list[str], today: date | None = None) -> list[str]:
    today = today or date.today()
    problems = []
    for line in lines:
        for dash in FORBIDDEN_DASHES:
            if dash in line:
                problems.append(f"en or em dash, use a spaced hyphen: {line!r}")

        ranges = list(DATE_RANGE.finditer(line))
        for match in ANY_MONTH_YEAR.finditer(line):
            if not any(r.start() <= match.start() < r.end() for r in ranges):
                problems.append(f"date not in MM/YYYY - MM/YYYY form: {match.group(0)!r}")

        for r in ranges:
            start = date(int(r.group(2)), int(r.group(1)), 1)
            end = date(int(r.group(4)), int(r.group(3)), 1) if r.group(3) else today
            if start > end:
                problems.append(f"range ends before it starts: {r.group(0)!r}")
    return problems
