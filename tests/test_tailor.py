from datetime import date

import pytest

from resume_agent.documents import Role, parse_resume
from resume_agent.ledger import load_ledger
from resume_agent.tailor import (
    TailorError,
    apply_plan,
    bank_markdown,
    build_bank,
    diff_markdown,
    drop_lowest_bullet,
    experience_roles,
    known_skill_rows,
    ledger_summary,
    numbers,
    without_roles,
)

CURRENT = "Software Engineer @ Acme Health, 01/2023 - present"
EARLIER = "Field Technician @ Globex, 01/2016 - 11/2019"
BASELINE = parse_resume(
    f"""---
headline: Software Engineer | TypeScript
---
## Experience
### {CURRENT}
- Built dozens of AWS Lambda functions serving 1.3M requests a day.
- Wrote Vitest tests.
### {EARLIER}
## Education
BSc, Computer Science, State University
## Skills
- Languages: TypeScript, Python
"""
)
EXTRA = parse_resume(
    f"""## Experience
### {CURRENT}
- Built 100+ AWS Lambda functions as traffic grew 43x.
- Wrote Vitest tests.
"""
)
LEDGER_YAML = """
roles:
  Acme Health:
    from: 01/2023
    to: present
skills:
  TypeScript:
    - role: Acme Health
  Python:
    - months: 4
      where: [Initrode Bank]
  AWS Lambda:
    - role: Acme Health
  Vitest:
    - role: Acme Health
metrics:
  deploy_time_cut: "38%"
"""


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "skills-ledger.yaml"
    path.write_text(LEDGER_YAML)
    return load_ledger(path, date(2026, 11, 21))


@pytest.fixture
def bank():
    return build_bank(BASELINE, EXTRA)


def plan(**overrides) -> dict:
    base = {
        "headline": "Backend Engineer | TypeScript | AWS",
        "roles": [
            {
                "heading": CURRENT,
                "bullets": [
                    {
                        "source": "B3",
                        "text": "Built 100+ AWS Lambda functions in TypeScript; traffic grew 43x.",
                    },
                    {
                        "source": "B2",
                        "text": "Wrote Vitest tests.",
                    },
                ],
            },
        ],
        "skills": ["Cloud: AWS (Lambda)", "Languages: TypeScript"],
    }
    return {
        **base,
        **overrides,
    }


def test_bank_merges_baseline_and_extra_without_duplicates(bank):
    assert [(bullet.id, bullet.text[:12]) for bullet in bank] == [
        ("B1", "Built dozens"),
        ("B2", "Wrote Vitest"),
        ("B3", "Built 100+ A"),
    ]
    assert bank_markdown(bank).startswith(f"### {CURRENT}\n- B1: Built dozens")


def test_without_roles_drops_roles_by_company():
    trimmed = without_roles(BASELINE, ["globex"])

    assert [role.title for role in experience_roles(trimmed)] == [CURRENT]
    assert [role.title for role in experience_roles(BASELINE)] == [CURRENT, EARLIER]


@pytest.mark.parametrize(
    ("title", "company"),
    [
        (CURRENT, "Acme Health"),
        ("Engineer @ Acme, Inc., 01/2020 - 05/2022", "Acme, Inc."),
        ("Engineer @ Globex", "Globex"),
        ("Freelance", ""),
    ],
)
def test_role_company(title, company):
    assert Role(title).company == company


def test_ledger_summary(ledger):
    assert "- Python: 4 months (Initrode Bank)" in ledger_summary(ledger)


def test_numbers_normalize_units():
    assert numbers("Grew 43x from 30K to 1.3M, cut 38%, 100+ Lambdas") == {
        "43x",
        "30k",
        "1.3m",
        "38%",
        "100+",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Shipped 18 microservices.", {"18"}),
        ("Shipped 18 services", {"18"}),
        ("Joined in 2023.", {"2023"}),
        ("Handled 1,300 requests", {"1300"}),
    ],
)
def test_numbers_ignore_following_words_and_periods(text, expected):
    assert numbers(text) == expected


@pytest.mark.parametrize(
    ("term", "known"),
    [
        ("TypeScript", True),
        ("Lambda", True),
        ("AWS", True),
        ("Java", False),
        ("Kubernetes", False),
        ("TypeScript Generics", False),
        ("AWS Lambda", True),
    ],
)
def test_ledger_knows(ledger, term, known):
    assert ledger.knows(term) is known


def test_valid_plan_builds_resume(ledger, bank):
    tailored = apply_plan(plan(), BASELINE, bank, ledger)

    experience = tailored.resume.sections[0]
    assert tailored.resume.headline == "Backend Engineer | TypeScript | AWS"
    assert experience.roles[0].bullets[0].startswith("Built 100+ AWS Lambda")
    assert experience.roles[1].title == EARLIER
    assert experience.roles[1].bullets == []
    assert tailored.resume.sections[1].paragraphs == ["BSc, Computer Science, State University"]
    assert tailored.resume.sections[2].items == ["Cloud: AWS (Lambda)", "Languages: TypeScript"]
    assert tailored.flags == []


def test_invented_number_is_rejected(ledger, bank):
    bad = plan(
        roles=[
            {
                "heading": CURRENT,
                "bullets": [
                    {
                        "source": "B1",
                        "text": "Built 50 AWS Lambda functions serving 1.3M requests a day.",
                    },
                ],
            },
        ]
    )

    with pytest.raises(TailorError, match="B1: number '50' is not in the source bullet"):
        apply_plan(bad, BASELINE, bank, ledger)


def test_ledger_metrics_allow_a_number(ledger, bank):
    ok = plan(
        roles=[
            {
                "heading": CURRENT,
                "bullets": [
                    {
                        "source": "B2",
                        "text": "Wrote Vitest tests that helped cut deploy time 38%.",
                    },
                ],
            },
        ]
    )

    assert apply_plan(ok, BASELINE, bank, ledger).bullets[0].source.id == "B2"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "roles": [
                    {
                        "heading": CURRENT,
                        "bullets": [
                            {
                                "source": "B9",
                                "text": "x",
                            },
                        ],
                    },
                ],
            },
            "bullet source 'B9' is not in the bank",
        ),
        (
            {
                "roles": [
                    {
                        "heading": "Staff Engineer @ Acme Health, 01/2023 - present",
                        "bullets": [],
                    },
                ],
            },
            "Unknown role heading",
        ),
        ({"roles": []}, f"Role '{CURRENT}' has no bullets"),
        (
            {
                "roles": [
                    {
                        "heading": CURRENT,
                        "bullets": [],
                    },
                ],
            },
            f"Role '{CURRENT}' has no bullets",
        ),
        (
            {
                "roles": [
                    {
                        "heading": CURRENT,
                        "bullets": [
                            {
                                "source": "B2",
                                "text": "Wrote Vitest tests.",
                            },
                            {
                                "source": "B2",
                                "text": "Wrote Vitest tests.",
                            },
                        ],
                    },
                ],
            },
            "B2: used more than once",
        ),
        (
            {
                "roles": [
                    {
                        "heading": CURRENT,
                        "bullets": ["Wrote tests."],
                    },
                ],
            },
            "is not an object with source and text",
        ),
        ({"skills": ["Cloud: Kubernetes"]}, "Every skill is outside the skills ledger"),
        ({"skills": []}, "Skills list is empty"),
        ({"headline": ""}, "Headline is empty"),
    ],
)
def test_rule_breaks(ledger, bank, overrides, message):
    with pytest.raises(TailorError, match=message):
        apply_plan(plan(**overrides), BASELINE, bank, ledger)


def test_skills_outside_the_ledger_are_dropped_and_flagged(ledger, bank):
    mixed = plan(skills=["Cloud: AWS (Lambda), Kubernetes", "Ops: Terraform"])

    tailored = apply_plan(mixed, BASELINE, bank, ledger)

    assert tailored.resume.sections[2].items == ["Cloud: AWS (Lambda)"]
    assert tailored.flags == [
        "Dropped skill 'Kubernetes': not in the skills ledger",
        "Dropped skill 'Terraform': not in the skills ledger",
    ]


def test_known_skill_rows_keep_unlabeled_rows_and_drop_emptied_ones(ledger):
    rows = ["AWS (Lambda), Go", "Ops: Terraform", "Cloud: AWS (Lambda, Kubernetes)"]

    assert known_skill_rows(rows, ledger) == (
        ["AWS (Lambda)"],
        ["Go", "Terraform", "AWS (Lambda, Kubernetes)"],
    )


def test_years_and_proficiency_are_flagged(ledger, bank):
    flagged = plan(headline="Expert TypeScript Engineer | 5+ years")

    tailored = apply_plan(flagged, BASELINE, bank, ledger)

    assert tailored.flags == [
        "Headline: 'Expert' in 'Expert TypeScript Engineer | 5+ years'",
        "Headline: '5+ years' in 'Expert TypeScript Engineer | 5+ years'",
    ]


def test_drop_lowest_bullet_trims_the_longest_role_to_two(ledger, bank):
    three = plan(
        roles=[
            {
                "heading": CURRENT,
                "bullets": [
                    {
                        "source": "B3",
                        "text": "Built 100+ AWS Lambda functions; traffic grew 43x.",
                    },
                    {
                        "source": "B1",
                        "text": "Built dozens of AWS Lambda functions serving 1.3M requests a day.",
                    },
                    {
                        "source": "B2",
                        "text": "Wrote Vitest tests.",
                    },
                ],
            },
        ]
    )
    tailored = apply_plan(three, BASELINE, bank, ledger)

    first = drop_lowest_bullet(tailored)
    second = drop_lowest_bullet(tailored)

    assert first.source.id == "B2"
    assert second is None
    assert len(tailored.resume.sections[0].roles[0].bullets) == 2
    assert tailored.flags == ["Dropped to fit one page: B2"]
    assert "- Not used: B2" in diff_markdown(BASELINE, tailored, bank)


def test_diff_shows_every_change(ledger, bank):
    tailored = apply_plan(plan(), BASELINE, bank, ledger)

    diff = diff_markdown(BASELINE, tailored, bank)

    assert "- Software Engineer | TypeScript\n+ Backend Engineer | TypeScript | AWS" in diff
    assert "- [B3] reworded:" in diff
    assert "- [B2] unchanged: Wrote Vitest tests." in diff
    assert "- Not used: B1" in diff
    assert "+ Cloud: AWS (Lambda)" in diff
    assert "Nothing touches years or proficiency." in diff
