"""Unit tests for linkedin_scraper.sourcing.skills.aggregate_skills."""

import pytest

from linkedin_scraper.models.github import GitHubCandidateSummary
from linkedin_scraper.models.person import Person
from linkedin_scraper.models.resume import ResumeData, ResumeProject
from linkedin_scraper.sourcing.skills import (
    SOURCE_GITHUB_TECHNOLOGY,
    SOURCE_LINKEDIN_SKILL,
    SOURCE_RESUME,
    SOURCE_RESUME_PROJECT,
    aggregate_skills,
)


def _github_summary(top_technologies=None) -> GitHubCandidateSummary:
    return GitHubCandidateSummary(top_technologies=top_technologies or [])


def _person(skills=None) -> Person:
    return Person(linkedin_url="https://linkedin.com/in/janedoe", skills=skills or [])


@pytest.mark.unit
class TestAggregateSkills:
    def test_empty_when_no_sources(self):
        assert aggregate_skills(None, None, None) == []

    def test_resume_skills_included(self):
        resume = ResumeData(skills=["Python", "Go"])
        entries = aggregate_skills(resume, None, None)
        assert {e.name for e in entries} == {"Python", "Go"}
        assert all(e.sources == [SOURCE_RESUME] for e in entries)

    def test_resume_project_technologies_included(self):
        resume = ResumeData(projects=[ResumeProject(name="p", technologies=["React", "Node"])])
        entries = aggregate_skills(resume, None, None)
        assert {e.name for e in entries} == {"React", "Node"}
        assert all(e.sources == [SOURCE_RESUME_PROJECT] for e in entries)

    def test_linkedin_skills_included(self):
        person = _person(skills=["Kubernetes", "Terraform"])
        entries = aggregate_skills(None, None, person)
        assert {e.name for e in entries} == {"Kubernetes", "Terraform"}
        assert all(e.sources == [SOURCE_LINKEDIN_SKILL] for e in entries)

    def test_github_top_technologies_included(self):
        github_summary = _github_summary(top_technologies=["Go", "react"])
        entries = aggregate_skills(None, github_summary, None)
        by_name = {e.name: e.sources for e in entries}
        assert by_name["Go"] == [SOURCE_GITHUB_TECHNOLOGY]
        assert by_name["react"] == [SOURCE_GITHUB_TECHNOLOGY]

    def test_dedupes_case_insensitively_and_unions_sources(self):
        resume = ResumeData(skills=["React"])
        github_summary = _github_summary(top_technologies=["react"])
        entries = aggregate_skills(resume, github_summary, None)
        assert len(entries) == 1
        assert entries[0].name == "React"
        assert set(entries[0].sources) == {SOURCE_RESUME, SOURCE_GITHUB_TECHNOLOGY}

    def test_blank_names_skipped(self):
        resume = ResumeData(skills=["", "  ", "Python"])
        entries = aggregate_skills(resume, None, None)
        assert [e.name for e in entries] == ["Python"]
