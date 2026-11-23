from datetime import date

import pytest

from resume_agent.ledger import (
    LedgerError,
    Period,
    load_ledger,
    merged_months,
    whole_years,
    without_ledger_roles,
)

TODAY = date(2026, 11, 21)
LEDGER = """
roles:
  Acme Health:
    from: 01/2023
    to: present
  Initrode Bank:
    from: 08/2022
    to: 11/2022
  Initech:
    from: 05/2021
    to: 08/2022
skills:
  TypeScript:
    - role: Acme Health
    - role: Initrode Bank
    - role: Initech
  Python:
    - role: Initrode Bank
  SQL:
    - months: 3
      where: [Acme Health, Initech]
  Kotlin:
    - from: 02/2024
      to: 07/2024
      where: [Acme Health]
metrics:
  lambda_functions: "100+"
"""


WITH_INITECH_ONLY_SKILL = LEDGER.replace("metrics:", "  Go:\n    - role: Initech\nmetrics:")


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "skills-ledger.yaml"
    path.write_text(LEDGER)
    return load_ledger(path, TODAY)


def write(tmp_path, text):
    path = tmp_path / "skills-ledger.yaml"
    path.write_text(text)
    return path


def test_dropped_role_moves_capped_skill_credit(tmp_path):
    ledger = load_ledger(write(tmp_path, WITH_INITECH_ONLY_SKILL), TODAY)

    moved = without_ledger_roles(ledger, ["initech"], "Initrode Bank", 3)

    acme_and_initrode = merged_months([moved.roles["Acme Health"], moved.roles["Initrode Bank"]])
    assert "Initech" not in moved.roles
    assert moved.experience_months() == acme_and_initrode
    assert moved.skill_months("Go") == 3
    assert moved.usage("Go").where == ["Initrode Bank"]
    assert moved.skill_months("TypeScript") == acme_and_initrode
    assert moved.usage("SQL").where == ["Acme Health"]


def test_dropped_role_without_a_target_loses_its_credit(tmp_path):
    ledger = load_ledger(write(tmp_path, WITH_INITECH_ONLY_SKILL), TODAY)

    assert without_ledger_roles(ledger, ["Initech"], None, 3).skill_months("Go") == 0


def test_period_months_are_inclusive():
    assert Period(date(2022, 8, 1), date(2022, 11, 1)).months == 4


def test_merged_months_joins_overlapping_and_adjacent_periods():
    periods = [
        Period(date(2021, 5, 1), date(2022, 8, 1)),
        Period(date(2022, 9, 1), date(2022, 11, 1)),
        Period(date(2022, 10, 1), date(2022, 12, 1)),
        Period(date(2024, 1, 1), date(2024, 1, 1)),
    ]

    assert merged_months(periods) == 20 + 1


def test_skill_months(ledger):
    assert ledger.skill_months("Python") == 4
    assert ledger.skill_months("sql") == 3
    assert ledger.skill_months("Kotlin") == 6
    assert ledger.skill_months("TypeScript") == 19 + 47
    assert ledger.skill_months("Rust") == 0


def test_experience_and_whole_years(ledger):
    assert ledger.experience_months() == 66
    assert whole_years(ledger.experience_months()) == 5


def test_usage_records_where(ledger):
    assert ledger.usage("SQL").where == ["Acme Health", "Initech"]
    assert ledger.metrics == {"lambda_functions": "100+"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("skills:\n  Go:\n    - role: Nowhere\n", "unknown role 'Nowhere'"),
        ("skills:\n  Go:\n    - months: 0\n", "months must be a positive whole number"),
        ("skills:\n  Go:\n    - from: 13/2020\n      to: 01/2021\n", "Expected MM/YYYY"),
        ("skills:\n  Go:\n    - from: 02/2021\n      to: 01/2021\n", "ends before it starts"),
        ("skills:\n  Go:\n    - from: 02/2021\n", "needs both from and to"),
        ("skills:\n  Go:\n    - language\n", "expected role:, from/to, or months:"),
        ("roles: [unclosed", "not valid YAML"),
        ("roles:\n  Acme: 01/2020\n", "expected from: and to: on separate lines"),
        ("- a list\n", "must have roles:, skills: and metrics:"),
    ],
)
def test_invalid_ledgers(tmp_path, text, message):
    with pytest.raises(LedgerError, match=message):
        load_ledger(write(tmp_path, text), TODAY)


def test_missing_ledger(tmp_path):
    with pytest.raises(LedgerError, match="not found"):
        load_ledger(tmp_path / "missing.yaml", TODAY)
