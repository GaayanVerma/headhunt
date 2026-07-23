"""Unified, deduped, source-tagged skill list across LinkedIn, resume, and
GitHub signals.
"""

from typing import List, Optional

from pydantic import BaseModel

from ..models.github import GitHubCandidateSummary
from ..models.person import Person
from ..models.resume import ResumeData

SOURCE_LINKEDIN_SKILL = "linkedin_skill"
SOURCE_RESUME = "resume"
SOURCE_RESUME_PROJECT = "resume_project"
SOURCE_GITHUB_TECHNOLOGY = "github_technology"


class SkillEntry(BaseModel):
    name: str
    sources: List[str] = []


def _collect(
    person: Optional[Person],
    resume: Optional[ResumeData],
    github_summary: Optional[GitHubCandidateSummary],
) -> List[tuple]:
    """Returns [(name, source), ...] candidates in priority order."""
    candidates: List[tuple] = []

    if person is not None:
        candidates.extend((skill, SOURCE_LINKEDIN_SKILL) for skill in person.skills)

    if resume is not None:
        candidates.extend((skill, SOURCE_RESUME) for skill in resume.skills)
        for project in resume.projects:
            candidates.extend((tech, SOURCE_RESUME_PROJECT) for tech in project.technologies)

    if github_summary is not None:
        candidates.extend((tech, SOURCE_GITHUB_TECHNOLOGY) for tech in github_summary.top_technologies)

    return candidates


def aggregate_skills(
    resume: Optional[ResumeData] = None,
    github_summary: Optional[GitHubCandidateSummary] = None,
    person: Optional[Person] = None,
) -> List[SkillEntry]:
    """Dedupe skill candidates case-insensitively across sources, keeping
    the first-seen casing and unioning sources for names that recur."""
    entries: dict = {}
    order: List[str] = []

    for name, source in _collect(person, resume, github_summary):
        name = name.strip()
        if not name:
            continue
        key = name.lower()
        if key not in entries:
            entries[key] = SkillEntry(name=name, sources=[source])
            order.append(key)
        elif source not in entries[key].sources:
            entries[key].sources.append(source)

    return [entries[key] for key in order]
