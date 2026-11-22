from datetime import date, timedelta

import pytest

from resume_agent.config import Config
from resume_agent.job_listing import Listing
from resume_agent.triage import job_board, posting_age, sentences, triage_listing

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
        "Citizenship: Must be a U.S. citizen.",
        "Degree: Bachelor's degree in Computer Science required.",
    ]
    assert result.notes == [
        "Degree: Master's in a related field preferred.",
        "Work authorization: We are unable to provide visa sponsorship.",
    ]
    assert "Result: **FLAGGED**" in result.markdown()


def test_no_clearance_required_is_not_flagged(config):
    result = triage_listing(listing("No security clearance required. Remote."), config, TODAY)

    assert not result.flagged


def test_work_authorization_boilerplate_is_one_note(config):
    text = "We sponsor visas.\nNot every role qualifies for sponsorship.\nDo you require a visa?"

    result = triage_listing(listing(text), config, TODAY)

    assert result.notes == ["Work authorization: We sponsor visas. (+2 more)"]
