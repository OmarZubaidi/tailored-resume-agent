import pytest

from resume_agent.config import Config
from resume_agent.documents import parse_resume
from resume_agent.keywords import (
    coverage_detail,
    expand_term,
    keyword_coverage,
    mentions,
    skill_row_terms,
    split_top_level,
    vocabulary,
)

RESUME = parse_resume(
    """## Experience
### Software Engineer @ Acme Health, 01/2023 - present
- Built Node.js services on AWS Lambda with TypeScript and PostgreSQL.
## Skills
- Languages: TypeScript, Python, HTML/CSS
- Cloud: AWS (Lambda, CDK), CI/CD
"""
)


@pytest.fixture
def config(config_data) -> Config:
    return Config(**config_data)


def test_split_top_level_ignores_commas_in_parentheses():
    assert split_top_level("AWS (Lambda, CDK), Git") == ["AWS (Lambda, CDK)", "Git"]


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("AWS (Lambda, CDK)", ["AWS", "Lambda", "CDK"]),
        ("HTML/CSS", ["HTML", "CSS"]),
        ("CI/CD", ["CI/CD"]),
        ("Mocha/Chai", ["Mocha", "Chai"]),
    ],
)
def test_expand_term(term, expected):
    assert expand_term(term) == expected


def test_skill_row_terms_drop_label():
    assert skill_row_terms("Cloud: AWS (Lambda, CDK), CI/CD") == ["AWS", "Lambda", "CDK", "CI/CD"]


@pytest.mark.parametrize(
    ("term", "text", "expected"),
    [
        ("Node", "Experience with Node.js", True),
        ("REST", "Design REST APIs", True),
        ("Webhooks", "Webhook delivery", False),
        ("Java", "Strong JavaScript skills", False),
        ("C#", "C# and .NET", True),
        ("Express", "express interest", False),
        ("Express", "Built with Express", True),
        ("React", "React Native apps", True),
        ("Python", "we use python daily", True),
        ("pytest", "Tests in Pytest", True),
        ("REST", "the rest of the team", False),
    ],
)
def test_mentions(term, text, expected):
    assert mentions(term, text) is expected


def test_vocabulary_merges_bundled_industry_and_resume_skills(config):
    terms = vocabulary(RESUME, config)

    assert "Kubernetes" in terms
    assert "EHR" in terms
    assert "CDK" in terms


def test_keyword_coverage(config):
    listing = "We use TypeScript, Kubernetes, PostgreSQL and Terraform on AWS."

    coverage = keyword_coverage(listing, RESUME, config)

    assert coverage.listing_terms == ["AWS", "Kubernetes", "PostgreSQL", "Terraform", "TypeScript"]
    assert coverage.matched == ["AWS", "PostgreSQL", "TypeScript"]
    assert coverage.missing == ["Kubernetes", "Terraform"]
    assert coverage.ratio == pytest.approx(0.6)
    assert not coverage.stuffed
    assert coverage_detail(coverage).startswith("60% of 5 listing skills (target 40%-60%)")


def test_full_coverage_warns_about_stuffing(config):
    coverage = keyword_coverage("TypeScript and AWS", RESUME, config)

    assert coverage.stuffed
    assert "keyword stuffing" in coverage_detail(coverage)
