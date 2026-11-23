import json
from datetime import date, timedelta

import pytest

from resume_agent.config import Config
from resume_agent.job_listing import Listing
from resume_agent.llm import LlmError
from resume_agent.triage import (
    YEARS_FILE,
    Requirements,
    add_fit,
    company_from_url,
    extract_requirements,
    job_board,
    listing_years_max,
    posting_age,
    save_years,
    sentences,
    triage_listing,
)

TODAY = date(2026, 11, 21)


@pytest.fixture
def config(config_data) -> Config:
    return Config(
        **{
            **config_data,
            "location": "Springfield, IL",
        }
    )


def listing(text: str, source: str = "https://jobs.acme.com/123") -> Listing:
    return Listing(source=source, title="Software Engineer", text=text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Posted 5 days ago", timedelta(days=5)),
        ("Posted 30+ days ago", timedelta(days=30)),
        ("posted 2 weeks ago", timedelta(weeks=2)),
        ("Posted today", timedelta(0)),
        ("Posted yesterday", timedelta(days=1)),
        ("Posted on November 10, 2026", timedelta(days=11)),
        ("Reposted 3 days ago", None),
        ("No date here", None),
    ],
)
def test_posting_age(text, expected):
    assert posting_age(text, TODAY) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://www.linkedin.com/jobs/view/1", "linkedin.com"),
        ("https://indeed.com/viewjob?jk=1", "indeed.com"),
        ("https://boards.greenhouse.io/acme/jobs/1", None),
        ("file: printed.pdf", None),
    ],
)
def test_job_board(source, expected):
    assert job_board(source) == expected


def test_sentences_keep_abbreviations_whole():
    assert sentences("Must be a U.S. citizen. Remote role.\nApply now") == [
        "Must be a U.S. citizen.",
        "Remote role.",
        "Apply now",
    ]


def test_clean_listing(config):
    result = triage_listing(listing("Remote role. Build React apps."), config, TODAY)

    assert not result.flagged
    assert result.notes == []
    assert "Result: **CLEAR**" in result.markdown()


def test_stale_posting_and_job_board_are_notes(config):
    result = triage_listing(
        listing("Posted 5 days ago. Remote.", "https://www.linkedin.com/jobs/view/1"), config, TODAY
    )

    assert not result.flagged
    assert result.notes[0] == "Posted about 5 days ago (older than 72 hours)."
    assert "employer's own careers page" in result.notes[1]


def test_onsite_away_from_home_is_flagged(config):
    result = triage_listing(listing("This role is onsite in Austin, TX."), config, TODAY)

    assert result.flags == ["Location: hybrid or onsite, and Springfield is not mentioned."]


def test_hybrid_near_home_is_a_good_note(config):
    result = triage_listing(listing("Hybrid, 2 days a week in Springfield."), config, TODAY)

    assert not result.flagged
    assert result.notes == ["Hybrid or onsite near Springfield: a good sign."]


def test_hybrid_with_remote_option_is_not_flagged(config):
    result = triage_listing(listing("Hybrid in Austin or fully remote."), config, TODAY)

    assert not result.flagged


def test_knockouts(config):
    text = (
        "Active TS/SCI clearance required.\n"
        "Must be a U.S. citizen.\n"
        "We are unable to provide visa sponsorship.\n"
        "Bachelor's degree in Computer Science required.\n"
        "Master's in a related field preferred."
    )

    result = triage_listing(listing(text), config, TODAY)

    assert result.flags == [
        "Clearance: Active TS/SCI clearance required.",
        "Degree: Bachelor's degree in Computer Science required.",
    ]
    assert result.notes == [
        "Degree: Master's in a related field preferred.",
        "Work authorization: We are unable to provide visa sponsorship.",
    ]
    assert "Result: **FLAGGED**" in result.markdown()


def test_citizenship_requirements_are_ignored(config):
    text = "Remote. U.S. citizenship required; we do not sponsor visas."

    result = triage_listing(listing(text), config, TODAY)

    assert result.flags == []
    assert result.notes == []


def test_no_clearance_required_is_not_flagged(config):
    result = triage_listing(listing("No security clearance required. Remote."), config, TODAY)

    assert not result.flagged


LEDGER_YAML = """
roles:
  Acme:
    from: 05/2021
    to: 11/2026
skills:
  TypeScript:
    - role: Acme
  React:
    - role: Acme
"""


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / "skills-ledger.yaml"
    path.write_text(LEDGER_YAML)
    return path


def fit_reply(years, other=()):
    payload = {
        "years_required": years,
        "other_requirements": list(other),
    }
    return lambda _: f"```json\n{json.dumps(payload)}\n```"


def test_extract_requirements():
    requirements = extract_requirements(fit_reply(3, ["BS in CS"]), "LISTING")

    assert requirements == Requirements(3, ["BS in CS"])


def test_extract_requirements_reads_the_top_of_a_range():
    reply = '{"years_required": 2, "years_max": 4}'

    assert extract_requirements(lambda _: reply, "LISTING").years_max == 4


def test_fit_check_saves_years_for_tailoring(config, ledger_path, tmp_path):
    result = triage_listing(listing("Remote."), config, TODAY)
    reply = json.dumps({"years_max": 4})
    add_fit(result, "LISTING", ledger_path, lambda _: reply)

    save_years(tmp_path, result)

    assert listing_years_max(tmp_path, "LISTING", lambda _: "not called") == 4


def test_skipped_fit_check_clears_saved_years(config, tmp_path):
    (tmp_path / YEARS_FILE).write_text('{"years_max": 4}')

    save_years(tmp_path, triage_listing(listing("Remote."), config, TODAY))

    assert not (tmp_path / YEARS_FILE).exists()


@pytest.mark.parametrize("saved", ['{"years_max": 4', "[4]"])
def test_unreadable_saved_years_asks_again(tmp_path, saved):
    (tmp_path / YEARS_FILE).write_text(saved)
    reply = json.dumps({"years_max": 3})

    assert listing_years_max(tmp_path, "LISTING", lambda _: reply) == 3


@pytest.mark.parametrize("years_max", [True, "4", None])
def test_years_max_that_is_not_a_number_is_none(years_max):
    reply = json.dumps({"years_max": years_max})

    assert extract_requirements(lambda _: reply, "LISTING").years_max is None


def test_company_and_role_come_from_the_listing(config, ledger_path):
    reply = json.dumps(
        {
            "company": "Acme Health",
            "role": "Senior Software Engineer",
            "years_required": None,
            "other_requirements": [],
        }
    )
    result = triage_listing(listing("Remote."), config, TODAY)

    add_fit(result, "LISTING", ledger_path, lambda _: reply)

    assert (result.company, result.role) == ("Acme Health", "Senior Software Engineer")


def test_company_and_role_fall_back_to_url_and_title(config, ledger_path):
    result = triage_listing(listing("Remote."), config, TODAY)

    add_fit(result, "LISTING", ledger_path, fit_reply(None))

    assert (result.company, result.role) == ("Acme", "Software Engineer")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://job-boards.greenhouse.io/acme-health/jobs/1", "Acme Health"),
        ("https://jobs.ashbyhq.com/globex/f2e5", "Globex"),
        ("https://jobs.lever.co/initech/abc", "Initech"),
        ("https://umbrella.wd5.myworkdayjobs.com/en-US/careers/job/1", "Umbrella"),
        ("https://www.acme.com/careers/jobs/1", "Acme"),
        ("https://www.linkedin.com/jobs/view/123", ""),
        ("listing.pdf", ""),
    ],
)
def test_company_from_url(source, expected):
    assert company_from_url(source) == expected


def test_malformed_requirements_are_tolerated():
    reply = '{"years_required": true, "other_requirements": 3}'

    assert extract_requirements(lambda _: reply, "LISTING") == Requirements(None, [])


def test_fit_within_ledger_adds_no_flags(config, ledger_path):
    result = triage_listing(listing("Remote."), config, TODAY)

    add_fit(result, "LISTING", ledger_path, fit_reply(3))

    assert not result.flagged
    assert result.fit_checked
    assert "## Pending" not in result.markdown()


def test_too_many_years_is_flagged(config, ledger_path):
    result = add_fit(
        triage_listing(listing("Remote."), config, TODAY), "L", ledger_path, fit_reply(8)
    )

    assert result.flags == ["Years: the listing asks for 8, the ledger shows 5."]


def test_skills_outside_the_ledger_are_not_checked(config, ledger_path):
    reply = json.dumps(
        {
            "years_required": None,
            "required_skills": ["Go", "Rust", "Kotlin"],
            "other_requirements": ["BS in CS"],
        }
    )

    result = add_fit(
        triage_listing(listing("Remote."), config, TODAY), "L", ledger_path, lambda _: reply
    )

    assert not result.flagged
    assert result.notes == ["Requirement: BS in CS"]


def test_fit_skipped_without_ledger_still_names_company_and_role(config, tmp_path):
    reply = json.dumps(
        {
            "company": "Acme Health",
            "role": "Senior Software Engineer",
        }
    )
    result = triage_listing(listing("Remote."), config, TODAY)

    add_fit(result, "L", tmp_path / "none.yaml", lambda _: reply)

    assert result.notes[0].startswith("Fit check skipped: Skills ledger not found")
    assert "## Pending" in result.markdown()
    assert (result.company, result.role) == ("Acme Health", "Senior Software Engineer")


def test_fit_skipped_when_llm_fails(config, ledger_path):
    def broken_run(_):
        raise LlmError("usage limit reached")

    triage = triage_listing(listing("Remote."), config, TODAY)

    result = add_fit(triage, "L", ledger_path, broken_run)

    assert result.notes == ["Fit check skipped: usage limit reached"]


def test_work_authorization_boilerplate_is_one_note(config):
    text = "We sponsor visas.\nNot every role qualifies for sponsorship.\nDo you require a visa?"

    result = triage_listing(listing(text), config, TODAY)

    assert result.notes == ["Work authorization: We sponsor visas. (+2 more)"]
