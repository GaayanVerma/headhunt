"""Trims a full GitHubAnalysisResult down to what's actually needed for
candidate review: top-5 technologies, GitHub repos that look like real
projects but aren't already mentioned in the resume/LinkedIn (surfaced with
a link), and a personal portfolio/website URL if GitHub has one that isn't
already listed elsewhere. Pure, deterministic - no LLM, no network calls.

Project/portfolio "already mentioned" detection: exact URL match first
(normalized), then fuzzy name matching (token-overlap against resume raw
text/LinkedIn about, plus difflib.SequenceMatcher against explicit project
names from resume.projects[] and LinkedIn accomplishments where
category=="project").
"""

import re
from difflib import SequenceMatcher
from itertools import zip_longest
from typing import List, Optional, Set
from urllib.parse import urlparse

from ..models.github import GitHubAnalysisResult, GitHubCandidateSummary, UnlistedProject
from ..models.person import Person
from ..models.resume import ResumeData

_FUZZY_NAME_MATCH_THRESHOLD = 0.6
_TOKEN_OVERLAP_THRESHOLD = 0.6
_MAX_TOP_TECHNOLOGIES = 5


def _normalize_href(href: str) -> str:
    parsed = urlparse(href.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}".lower()


def _known_hrefs(person: Optional[Person], resume: Optional[ResumeData]) -> Set[str]:
    hrefs: Set[str] = set()
    if resume is not None:
        for href in [resume.github_url, resume.linkedin_url, *resume.other_urls]:
            if href:
                hrefs.add(_normalize_href(href))
    if person is not None:
        for contact in person.contacts:
            if contact.type == "website" and contact.value:
                hrefs.add(_normalize_href(contact.value))
    return hrefs


def _known_text_corpus(person: Optional[Person], resume: Optional[ResumeData]) -> str:
    parts: List[str] = []
    if resume is not None and resume.raw_text:
        parts.append(resume.raw_text)
    if person is not None and person.about:
        parts.append(person.about)
    return " ".join(parts).lower()


def _known_project_names(person: Optional[Person], resume: Optional[ResumeData]) -> List[str]:
    names: List[str] = []
    if resume is not None:
        names.extend(p.name for p in resume.projects if p.name)
    if person is not None:
        names.extend(a.title for a in person.accomplishments if a.category == "project" and a.title)
    return names


def _token_overlap_mentioned(repo_name: str, corpus: str) -> bool:
    if not corpus:
        return False
    tokens = [t for t in re.split(r"[^a-z0-9]+", repo_name.lower()) if len(t) > 2]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in corpus)
    return (hits / len(tokens)) >= _TOKEN_OVERLAP_THRESHOLD


def _fuzzy_name_mentioned(repo_name: str, known_names: List[str]) -> bool:
    lowered = repo_name.lower()
    return any(
        SequenceMatcher(None, lowered, name.lower()).ratio() >= _FUZZY_NAME_MATCH_THRESHOLD
        for name in known_names
    )


def _merge_top_technologies(aggregate_features) -> List[str]:
    """Interleave the (already top-5-capped) language and framework rollups,
    deduped case-insensitively, capped at 5 total."""
    languages = [lang.language for lang in aggregate_features.top_languages]
    frameworks = [fw.framework for fw in aggregate_features.top_frameworks]

    merged: List[str] = []
    seen: Set[str] = set()
    for lang, fw in zip_longest(languages, frameworks):
        for candidate in (lang, fw):
            if candidate and candidate.lower() not in seen:
                seen.add(candidate.lower())
                merged.append(candidate)
                if len(merged) >= _MAX_TOP_TECHNOLOGIES:
                    return merged
    return merged


def build_candidate_github_summary(
    github_facts: GitHubAnalysisResult,
    person: Optional[Person] = None,
    resume: Optional[ResumeData] = None,
) -> GitHubCandidateSummary:
    """Deterministic GitHubAnalysisResult -> GitHubCandidateSummary."""
    if github_facts.profile is None:
        return GitHubCandidateSummary(notes=github_facts.limitations.notes)

    agg = github_facts.aggregate_features
    known_hrefs = _known_hrefs(person, resume)
    corpus = _known_text_corpus(person, resume)
    known_project_names = _known_project_names(person, resume)

    unlisted_projects = []
    for repo in github_facts.repositories:
        if repo.is_fork:
            continue
        if _normalize_href(repo.url) in known_hrefs:
            continue
        if _token_overlap_mentioned(repo.name, corpus):
            continue
        if _fuzzy_name_mentioned(repo.name, known_project_names):
            continue
        unlisted_projects.append(
            UnlistedProject(name=repo.name, url=repo.url, description=repo.description)
        )

    unlisted_portfolio_url = None
    website = github_facts.profile.website_url
    if website and _normalize_href(website) not in known_hrefs:
        unlisted_portfolio_url = website

    return GitHubCandidateSummary(
        login=github_facts.profile.login,
        top_technologies=_merge_top_technologies(agg),
        unlisted_projects=unlisted_projects,
        unlisted_portfolio_url=unlisted_portfolio_url,
        original_repos_count=agg.original_repos_count,
        active_repos_90d=agg.active_repos_90d,
        documentation_coverage_ratio=agg.documentation_coverage_ratio,
        testing_coverage_ratio=agg.testing_coverage_ratio,
        ci_coverage_ratio=agg.ci_coverage_ratio,
        account_age_days=agg.account_age_days,
        notes=github_facts.limitations.notes,
    )
