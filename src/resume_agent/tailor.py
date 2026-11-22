import re
from dataclasses import dataclass, field, replace

from resume_agent.documents import Resume, Role, Section
from resume_agent.keywords import SKILLS_SECTION, skill_row_terms
from resume_agent.ledger import Ledger

BANK_FILE = "bullet-bank.md"
EXPERIENCE_SECTION = "Experience"
MIN_BULLETS_PER_ROLE = 2
NUMBER = re.compile(r"\d(?:[\d,.]*\d)?(?:\s?[%+]|[xKkMm](?![A-Za-z]))?")
PROFICIENCY = re.compile(
    r"\b(\d+\+?\s*(?:years?|yrs?)|expert|proficient|proficiency|advanced|mastery|seasoned|"
    r"extensive experience)\b",
    re.IGNORECASE,
)


class TailorError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Tailoring broke the rules:\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass(frozen=True)
class BankBullet:
    id: str
    heading: str
    text: str


@dataclass(frozen=True)
class ChosenBullet:
    heading: str
    source: BankBullet
    text: str


@dataclass
class Tailored:
    resume: Resume
    bullets: list[ChosenBullet] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def section(resume: Resume, title: str) -> Section | None:
    return next((item for item in resume.sections if item.title == title), None)


def experience_roles(resume: Resume | None) -> list[Role]:
    found = section(resume, EXPERIENCE_SECTION) if resume else None
    return found.roles if found else []


def build_bank(baseline: Resume, extra: Resume | None = None) -> list[BankBullet]:
    bank: list[BankBullet] = []
    seen: set[tuple[str, str]] = set()
    for role in experience_roles(baseline) + experience_roles(extra):
        for text in role.bullets:
            if (role.title, text) not in seen:
                seen.add((role.title, text))
                bank.append(BankBullet(id=f"B{len(bank) + 1}", heading=role.title, text=text))
    return bank


def bank_markdown(bank: list[BankBullet]) -> str:
    lines: list[str] = []
    for bullet in bank:
        heading = f"### {bullet.heading}"
        if heading not in lines:
            lines.extend(["", heading])
        lines.append(f"- {bullet.id}: {bullet.text}")
    return "\n".join(lines).strip()


def ledger_summary(ledger: Ledger) -> str:
    lines = []
    for skill, usage in ledger.skills.items():
        where = ", ".join(dict.fromkeys(usage.where))
        lines.append(f"- {skill}: {ledger.skill_months(skill)} months ({where})")
    return "\n".join(lines)


def numbers(text: str) -> set[str]:
    return {match.replace(" ", "").replace(",", "").lower() for match in NUMBER.findall(text)}


def proficiency_flags(label: str, text: str) -> list[str]:
    return [f"{label}: {match.group(0)!r} in {text!r}" for match in PROFICIENCY.finditer(text)]


def check_bullet(text: str, source: BankBullet, ledger: Ledger) -> list[str]:
    allowed = numbers(source.text) | numbers(" ".join(ledger.metrics.values()))
    return [
        f"{source.id}: number {number!r} is not in the source bullet or the ledger metrics"
        for number in sorted(numbers(text) - allowed)
    ]


def choose_bullets(
    plan_roles: dict[str, list], heading: str, bank: dict[str, BankBullet], ledger: Ledger
) -> tuple[list[ChosenBullet], list[str], list[str]]:
    chosen, problems, flags = [], [], []
    for item in plan_roles.get(heading, []):
        if not isinstance(item, dict):
            problems.append(f"{heading}: bullet {item!r} is not an object with source and text")
            continue
        source = bank.get(str(item.get("source", "")))
        text = str(item.get("text", "")).strip()
        if source is None:
            problems.append(f"{heading}: bullet source {item.get('source')!r} is not in the bank")
            continue
        if source.heading != heading:
            problems.append(f"{source.id}: belongs to {source.heading!r}, not {heading!r}")
            continue
        if any(bullet.source == source for bullet in chosen):
            problems.append(f"{source.id}: used more than once")
            continue
        if not text:
            problems.append(f"{source.id}: empty bullet text")
            continue
        problems.extend(check_bullet(text, source, ledger))
        flags.extend(proficiency_flags(source.id, text))
        chosen.append(ChosenBullet(heading=heading, source=source, text=text))
    return chosen, problems, flags


def apply_plan(plan: dict, baseline: Resume, bank: list[BankBullet], ledger: Ledger) -> Tailored:
    problems: list[str] = []
    flags: list[str] = []
    by_id = {bullet.id: bullet for bullet in bank}
    baseline_headings = [role.title for role in experience_roles(baseline)]

    plan_roles = {
        str(role.get("heading", "")): role.get("bullets", []) for role in plan.get("roles", [])
    }
    problems += [f"Unknown role heading {h!r}" for h in plan_roles if h not in baseline_headings]
    problems += [
        f"Role {role.title!r} has no bullets"
        for role in experience_roles(baseline)
        if role.bullets and not plan_roles.get(role.title)
    ]

    headline = str(plan.get("headline", "")).strip()
    if not headline:
        problems.append("Headline is empty")
    flags += proficiency_flags("Headline", headline)

    roles, chosen = [], []
    for role in experience_roles(baseline):
        picked, role_problems, role_flags = choose_bullets(plan_roles, role.title, by_id, ledger)
        problems += role_problems
        flags += role_flags
        chosen += picked
        roles.append(replace(role, bullets=[bullet.text for bullet in picked]))

    skills = [str(row).strip() for row in plan.get("skills") or [] if str(row).strip()]
    baseline_skills = section(baseline, SKILLS_SECTION)
    if baseline_skills and baseline_skills.items and not skills:
        problems.append("Skills list is empty")
    problems += [
        f"Skill {term!r} is not in the skills ledger"
        for row in skills
        for term in skill_row_terms(row)
        if not ledger.knows(term)
    ]

    if problems:
        raise TailorError(problems)

    sections = []
    for item in baseline.sections:
        if item.title == EXPERIENCE_SECTION:
            item = replace(item, roles=roles)
        elif item.title == SKILLS_SECTION:
            item = replace(item, items=skills)
        sections.append(item)
    return Tailored(
        resume=Resume(headline=headline, sections=sections),
        bullets=chosen,
        flags=flags,
    )


def drop_lowest_bullet(tailored: Tailored) -> ChosenBullet | None:
    roles = [r for r in experience_roles(tailored.resume) if len(r.bullets) > MIN_BULLETS_PER_ROLE]
    if not roles:
        return None
    role = max(roles, key=lambda item: len(item.bullets))
    text = role.bullets.pop()
    dropped = next(
        bullet
        for bullet in reversed(tailored.bullets)
        if bullet.heading == role.title and bullet.text == text
    )
    tailored.bullets.remove(dropped)
    tailored.flags.append(f"Dropped to fit one page: {dropped.source.id}")
    return dropped


def diff_markdown(baseline: Resume, tailored: Tailored, bank: list[BankBullet]) -> str:
    lines = [
        "# Changes from the baseline",
        "",
        "## Review",
        *(f"- {flag}" for flag in tailored.flags or ["Nothing touches years or proficiency."]),
        "",
        "## Headline",
        f"- {baseline.headline}",
        f"+ {tailored.resume.headline}",
        "",
        "## Experience",
    ]
    used = {bullet.source.id for bullet in tailored.bullets}
    for role in experience_roles(tailored.resume):
        lines.extend(["", f"### {role.title}"])
        for bullet in (item for item in tailored.bullets if item.heading == role.title):
            if bullet.text == bullet.source.text:
                lines.append(f"- [{bullet.source.id}] unchanged: {bullet.text}")
            else:
                lines.extend(
                    [
                        f"- [{bullet.source.id}] reworded:",
                        f"  - {bullet.source.text}",
                        f"  + {bullet.text}",
                    ]
                )
        dropped = [b.id for b in bank if b.heading == role.title and b.id not in used]
        if dropped:
            lines.append(f"- Not used: {', '.join(dropped)}")

    before = section(baseline, SKILLS_SECTION)
    after = section(tailored.resume, SKILLS_SECTION)
    lines.extend(["", "## Skills"])
    lines.extend(f"- {row}" for row in (before.items if before else []))
    lines.extend(f"+ {row}" for row in (after.items if after else []))
    return "\n".join(lines) + "\n"
