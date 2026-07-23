"""Unit tests for github.candidate_summary.build_candidate_github_summary -
deterministic, no network/LLM calls."""

from datetime import datetime, timezone

import pytest

from linkedin_scraper.github.candidate_summary import build_candidate_github_summary
from linkedin_scraper.models.github import (
    AggregateFeatures,
    FrameworkRollup,
    GitHubAnalysisResult,
    GitHubProfile,
    LanguageRollup,
    ParserMetadata,
    Repository,
    SourceMetadata,
)
from linkedin_scraper.models.person import Accomplishment, Contact, Person
from linkedin_scraper.models.resume import ResumeData, ResumeProject


def _repo(name, url=None, is_fork=False, description=None) -> Repository:
    return Repository(
        id=name,
        name=name,
        full_name=f"janedoe/{name}",
        url=url or f"https://github.com/janedoe/{name}",
        owner_login="janedoe",
        owner_type="USER",
        is_fork=is_fork,
        description=description,
    )


def _github_facts(repos=None, top_languages=None, top_frameworks=None, website_url=None) -> GitHubAnalysisResult:
    return GitHubAnalysisResult(
        source_metadata=SourceMetadata(input_url_raw="https://github.com/janedoe", fetched_at=datetime.now(timezone.utc)),
        parser_metadata=ParserMetadata(analyzer_version="1"),
        profile=GitHubProfile(login="janedoe", website_url=website_url),
        repositories=repos or [],
        aggregate_features=AggregateFeatures(
            top_languages=[LanguageRollup(language=l, repo_count=1, total_bytes=100) for l in (top_languages or [])],
            top_frameworks=[FrameworkRollup(framework=f, repo_count=1) for f in (top_frameworks or [])],
        ),
    )


@pytest.mark.unit
class TestTopTechnologies:
    def test_merges_languages_and_frameworks_capped_at_five(self):
        facts = _github_facts(top_languages=["Go", "Python", "Rust"], top_frameworks=["React", "Django", "FastAPI"])
        summary = build_candidate_github_summary(facts)
        assert len(summary.top_technologies) == 5
        assert summary.top_technologies[0] == "Go"
        assert summary.top_technologies[1] == "React"

    def test_dedupes_case_insensitively(self):
        facts = _github_facts(top_languages=["Python"], top_frameworks=["python"])
        summary = build_candidate_github_summary(facts)
        assert summary.top_technologies == ["Python"]

    def test_no_profile_returns_empty_summary(self):
        facts = GitHubAnalysisResult(
            source_metadata=SourceMetadata(input_url_raw="https://github.com/ghost", fetched_at=datetime.now(timezone.utc)),
            parser_metadata=ParserMetadata(analyzer_version="1"),
        )
        summary = build_candidate_github_summary(facts)
        assert summary.top_technologies == []
        assert summary.unlisted_projects == []


@pytest.mark.unit
class TestUnlistedProjects:
    def test_repo_url_exact_match_excluded(self):
        facts = _github_facts(repos=[_repo("cool-app")])
        resume = ResumeData(github_url="https://github.com/janedoe/cool-app")
        summary = build_candidate_github_summary(facts, resume=resume)
        assert summary.unlisted_projects == []

    def test_repo_url_case_and_trailing_slash_normalized(self):
        facts = _github_facts(repos=[_repo("cool-app", url="https://github.com/janedoe/cool-app")])
        resume = ResumeData(other_urls=["https://GitHub.com/janedoe/cool-app/"])
        summary = build_candidate_github_summary(facts, resume=resume)
        assert summary.unlisted_projects == []

    def test_fuzzy_name_match_via_raw_text_excluded(self):
        facts = _github_facts(repos=[_repo("distributed-cache")])
        resume = ResumeData(raw_text="Built a distributed cache system in Go used at scale.")
        summary = build_candidate_github_summary(facts, resume=resume)
        assert summary.unlisted_projects == []

    def test_fuzzy_name_match_via_resume_project_name_excluded(self):
        facts = _github_facts(repos=[_repo("headhunt-scraper")])
        resume = ResumeData(projects=[ResumeProject(name="headhunt scraper tool", technologies=["Python"])])
        summary = build_candidate_github_summary(facts, resume=resume)
        assert summary.unlisted_projects == []

    def test_fuzzy_name_match_via_linkedin_accomplishment_excluded(self):
        facts = _github_facts(repos=[_repo("resume-parser")])
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            accomplishments=[Accomplishment(category="project", title="Resume Parser")],
        )
        summary = build_candidate_github_summary(facts, person=person)
        assert summary.unlisted_projects == []

    def test_truly_unlisted_repo_surfaced(self):
        facts = _github_facts(repos=[_repo("side-project-xyz", description="A weekend hack")])
        resume = ResumeData(raw_text="Experienced backend engineer with Python and Go.")
        summary = build_candidate_github_summary(facts, resume=resume)
        assert len(summary.unlisted_projects) == 1
        assert summary.unlisted_projects[0].name == "side-project-xyz"
        assert summary.unlisted_projects[0].description == "A weekend hack"

    def test_forks_excluded(self):
        facts = _github_facts(repos=[_repo("forked-repo", is_fork=True)])
        summary = build_candidate_github_summary(facts)
        assert summary.unlisted_projects == []


@pytest.mark.unit
class TestPortfolioDetection:
    def test_surfaces_unlisted_portfolio_url(self):
        facts = _github_facts(website_url="https://janedoe.dev")
        summary = build_candidate_github_summary(facts)
        assert summary.unlisted_portfolio_url == "https://janedoe.dev"

    def test_suppresses_portfolio_url_already_in_resume(self):
        facts = _github_facts(website_url="https://janedoe.dev")
        resume = ResumeData(other_urls=["https://janedoe.dev/"])
        summary = build_candidate_github_summary(facts, resume=resume)
        assert summary.unlisted_portfolio_url is None

    def test_suppresses_portfolio_url_already_in_linkedin_contacts(self):
        facts = _github_facts(website_url="https://janedoe.dev")
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            contacts=[Contact(type="website", value="https://janedoe.dev")],
        )
        summary = build_candidate_github_summary(facts, person=person)
        assert summary.unlisted_portfolio_url is None

    def test_none_when_no_website(self):
        facts = _github_facts()
        summary = build_candidate_github_summary(facts)
        assert summary.unlisted_portfolio_url is None
