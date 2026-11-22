import re
from dataclasses import dataclass, field
from datetime import date

import yaml

FRONT_MATTER_DELIMITER = "---"
MONTH_YEAR = r"(0[1-9]|1[0-2])/(\d{4})"
PRESENT = "present"
DATE_RANGE = re.compile(rf"\b{MONTH_YEAR} - (?:{MONTH_YEAR}|{PRESENT})\b")
WHOLE_MONTH_YEAR = re.compile(rf"^{MONTH_YEAR}$")
PLACEHOLDER = re.compile(r"\[[^\]\n]+\]")
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


@dataclass
class CoverLetter:
    title: str
    paragraphs: list[str]
    closing: str

    def text_lines(self) -> list[str]:
        return [line for line in [self.title, *self.paragraphs, self.closing] if line]


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


def parse_cover_letter(text: str) -> CoverLetter:
    meta, lines = split_front_matter(text)
    blocks: list[list[str]] = [[]]
    for line in lines:
        if line.strip():
            blocks[-1].append(line.strip())
        elif blocks[-1]:
            blocks.append([])
    paragraphs = [" ".join(block) for block in blocks if block]
    if len(paragraphs) < 2:
        raise DocumentError("Cover letter needs body paragraphs and a closing line")
    return CoverLetter(
        title=str(meta.get("title", "Cover Letter")),
        paragraphs=paragraphs[:-1],
        closing=paragraphs[-1],
    )


def open_placeholders(lines: list[str]) -> list[str]:
    return [match for line in lines for match in PLACEHOLDER.findall(line)]


def parse_month(text: str, today: date | None = None) -> date:
    value = str(text).strip()
    if value == PRESENT:
        return (today or date.today()).replace(day=1)
    match = WHOLE_MONTH_YEAR.match(value)
    if not match:
        raise DocumentError(f"Expected MM/YYYY or {PRESENT!r}, got {value!r}")
    return date(int(match.group(2)), int(match.group(1)), 1)


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
            start = parse_month(f"{r.group(1)}/{r.group(2)}")
            end = parse_month(f"{r.group(3)}/{r.group(4)}") if r.group(3) else today
            if start > end:
                problems.append(f"range ends before it starts: {r.group(0)!r}")
    return problems
