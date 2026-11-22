from datetime import date

import pytest

from resume_agent.documents import (
    DocumentError,
    date_problems,
    open_placeholders,
    parse_cover_letter,
    parse_resume,
)

RESUME = """---
headline: Software Engineer · TypeScript · AWS
---

## Experience

### Software Engineer
Acme Health, 01/2023 - present
- Built Lambdas.
- Built React apps.

### Junior Software Engineer
Initech, 05/2021 - 08/2022
- Built prototypes.

Earlier career: Field Technician, Globex (01/2016 - 11/2019)

## Education

### BSc, Computer Science
State University

## Skills

- Languages: TypeScript, Python
- Testing: Vitest, pytest
"""

TODAY = date(2026, 11, 21)


def test_parse_resume_structure():
    resume = parse_resume(RESUME)

    experience, education, skills = resume.sections
    assert resume.headline == "Software Engineer · TypeScript · AWS"
    assert [section.title for section in resume.sections] == ["Experience", "Education", "Skills"]
    assert experience.roles[0].title == "Software Engineer"
    assert experience.roles[0].subtitle == "Acme Health, 01/2023 - present"
    assert experience.roles[0].bullets == ["Built Lambdas.", "Built React apps."]
    assert experience.paragraphs == ["Earlier career: Field Technician, Globex (01/2016 - 11/2019)"]
    assert education.roles[0].subtitle == "State University"
    assert skills.items == ["Languages: TypeScript, Python", "Testing: Vitest, pytest"]


def test_text_lines_in_reading_order():
    lines = parse_resume(RESUME).text_lines()

    assert lines[:4] == [
        "Software Engineer · TypeScript · AWS",
        "Experience",
        "Software Engineer",
        "Acme Health, 01/2023 - present",
    ]
    assert lines[-1] == "Testing: Vitest, pytest"


def test_content_before_first_section_is_rejected():
    with pytest.raises(DocumentError, match="Line 1"):
        parse_resume("stray line\n## Experience\n")


@pytest.mark.parametrize(
    ("front_matter", "message"),
    [
        ("headline: [unclosed", "not valid YAML"),
        ("- a list", "key: value pairs"),
    ],
)
def test_bad_front_matter_is_rejected(front_matter, message):
    with pytest.raises(DocumentError, match=message):
        parse_resume(f"---\n{front_matter}\n---\n## Experience\n")


def test_unclosed_front_matter_is_rejected():
    with pytest.raises(DocumentError, match="never closes"):
        parse_resume("---\nheadline: x\n## Experience\n")


def test_parse_cover_letter():
    letter = parse_cover_letter(
        "Dear Hiring Manager,\n\nFirst line\ncontinues here.\n\nSecond paragraph.\n\nBest,\n"
    )

    assert letter.title == "Cover Letter"
    assert letter.paragraphs == [
        "Dear Hiring Manager,",
        "First line continues here.",
        "Second paragraph.",
    ]
    assert letter.closing == "Best,"


def test_cover_letter_title_from_front_matter():
    letter = parse_cover_letter("---\ntitle: Letter\n---\nHello.\n\nBest,\n")

    assert letter.title == "Letter"


def test_cover_letter_without_closing_is_rejected():
    with pytest.raises(DocumentError, match="closing"):
        parse_cover_letter("Only one paragraph.\n")


def test_open_placeholders():
    lines = ["Dear [Hiring Manager's Name],", "Built (fast) things.", "I like [Company Name]."]

    assert open_placeholders(lines) == ["[Hiring Manager's Name]", "[Company Name]"]


def test_valid_dates_have_no_problems():
    assert date_problems(parse_resume(RESUME).text_lines(), TODAY) == []


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("Initrode Bank, 08/2022-11/2022", "not in MM/YYYY - MM/YYYY form"),
        ("Globex (01/2016 – 11/2019)", "en or em dash"),
        ("Globex (01/2016 — 11/2019)", "en or em dash"),
        ("Globex, 1/2016 - 11/2019", "not in MM/YYYY - MM/YYYY form"),
        ("Globex, 13/2016 - 11/2019", "not in MM/YYYY - MM/YYYY form"),
        ("Globex, 11/2019 - 01/2016", "ends before it starts"),
        ("Future, 01/2027 - present", "ends before it starts"),
    ],
)
def test_date_problems(line, message):
    problems = date_problems([line], TODAY)

    assert any(message in problem for problem in problems), problems
