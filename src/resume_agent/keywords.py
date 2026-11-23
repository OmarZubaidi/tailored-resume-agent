import re
from dataclasses import dataclass
from importlib.resources import files

from resume_agent.config import Config
from resume_agent.documents import Resume

BUNDLED_SKILLS = files("resume_agent").joinpath("templates/hard_skills.txt").read_text()
MIN_SLASH_PART = 3
TARGET_LOW = 0.4
TARGET_HIGH = 0.6
STUFFING_THRESHOLD = 0.8
SKILLS_SECTION = "Skills"
COMMON_WORD_TERMS = {
    "Chai",
    "Express",
    "Helm",
    "Lambda",
    "Mocha",
    "Node",
    "REST",
    "Rust",
    "Spark",
    "Spring",
    "Swift",
}


@dataclass
class Coverage:
    listing_terms: list[str]
    matched: list[str]
    missing: list[str]

    @property
    def ratio(self) -> float:
        return len(self.matched) / len(self.listing_terms) if self.listing_terms else 0.0

    @property
    def stuffed(self) -> bool:
        return self.ratio > STUFFING_THRESHOLD


def split_top_level(text: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    return [part.strip() for part in [*parts, current] if part.strip()]


def expand_term(term: str) -> list[str]:
    head, _, inner = term.partition("(")
    terms = [head.strip()]
    if inner:
        terms.extend(split_top_level(inner.rstrip(")")))
    expanded = []
    for item in terms:
        pieces = item.split("/")
        if len(pieces) > 1 and all(len(piece) >= MIN_SLASH_PART for piece in pieces):
            expanded.extend(piece.strip() for piece in pieces)
        else:
            expanded.append(item)
    return [item for item in expanded if item]


def split_skill_row(row: str) -> tuple[str, list[str]]:
    label, separator, rest = row.partition(": ")
    if not separator:
        return "", split_top_level(row)
    return f"{label}{separator}", split_top_level(rest)


def skill_row_terms(row: str) -> list[str]:
    _, items = split_skill_row(row)
    return [term for item in items for term in expand_term(item)]


def vocabulary(resume: Resume, config: Config) -> list[str]:
    terms = {line.strip() for line in BUNDLED_SKILLS.splitlines() if line.strip()}
    for keywords in config.industry_keywords.values():
        terms.update(keywords)
    for section in resume.sections:
        if section.title == SKILLS_SECTION:
            for row in section.items:
                terms.update(skill_row_terms(row))
    return sorted(terms, key=str.lower)


def mentions(term: str, text: str) -> bool:
    flags = 0 if term in COMMON_WORD_TERMS else re.IGNORECASE
    pattern = rf"(?<![\w+#.]){re.escape(term)}s?(?![\w+#])"
    return re.search(pattern, text, flags) is not None


def keyword_coverage(listing_text: str, resume: Resume, config: Config) -> Coverage:
    resume_text = "\n".join(resume.text_lines())
    listing_terms = [term for term in vocabulary(resume, config) if mentions(term, listing_text)]
    matched = [term for term in listing_terms if mentions(term, resume_text)]
    missing = [term for term in listing_terms if term not in matched]
    return Coverage(listing_terms=listing_terms, matched=matched, missing=missing)


def coverage_detail(coverage: Coverage) -> str:
    target = f"target {TARGET_LOW:.0%}-{TARGET_HIGH:.0%}"
    if coverage.stuffed:
        target += f"; above {STUFFING_THRESHOLD:.0%} looks like keyword stuffing"
    missing = ", ".join(coverage.missing) or "none"
    share = f"{coverage.ratio:.0%} of {len(coverage.listing_terms)} listing skills"
    return f"{share} ({target}). Missing: {missing}"
