"""Adapter: extract's pipeline output -> headhunt-G's ingestion JSON contract.

Pure mapping/dedupe functions, no I/O. Consumed by
samples/export_to_headhunt.py. Produces a payload matching headhunt-G's
`candidateProfileSchema` / `evaluationResultSchema` (see
lib/domain/candidate.ts, lib/domain/evaluation.ts in the headhunt-G repo)
exactly, plus the `rawText`/`model` fields the ingestion route needs
alongside them.

Dimension rename map (extract's readiness dimensions -> headhunt-G's
evaluation_readiness.dimension enum):
    ownership_and_proactivity -> ownership
    execution_credibility     -> execution
    drive_and_ambition        -> ambition
    adaptability              -> learnability

skill_groups is derived from linkedin_scraper.sourcing.skills.aggregate_skills,
which merges LinkedIn skills, resume Skills/Projects sections, and GitHub's
top_technologies (deduped case-insensitively, source-tagged); it's empty
when none of the three carry a skill signal.
tag/context on experiences and education entries are populated from a
CareerTimeline (see evaluation.timeline_builder.build_career_timeline),
built internally from `person` - deterministic kind (education/internship/
full_time/.../unknown) and transition (first_role/promotion/transition/
function_change) classification, no LLM involved. Note that CareerTimeline's
per-entry `kind` (employment type) is NOT the same thing as headhunt-G's
`JourneyTag.kind` (promotion/transition/function/pivot) - see
_TRANSITION_TAG_MAP below, which maps the latter from `transition`, not
`kind`.
"""

from typing import List, Optional
from urllib.parse import urlparse

from ..evaluation.timeline_builder import build_career_timeline
from ..github.candidate_summary import build_candidate_github_summary
from ..models.github import GitHubAnalysisResult, GitHubCandidateSummary, Repository
from ..models.person import Person
from ..models.readiness import StartupReadinessEvaluation
from ..models.resume import ResumeData
from ..models.timeline import CareerTimeline
from ..sourcing.skills import (
    SOURCE_GITHUB_TECHNOLOGY,
    SOURCE_LINKEDIN_SKILL,
    SOURCE_RESUME,
    SOURCE_RESUME_PROJECT,
    aggregate_skills,
)


def _drop_none(d: dict) -> dict:
    """headhunt-G's zod schemas use `.optional()` without `.nullable()`, so
    an explicit `null` fails validation - optional fields must be omitted
    entirely when there's no value."""
    return {k: v for k, v in d.items() if v is not None}

_DIMENSION_RENAME = {
    "ownership_and_proactivity": "ownership",
    "execution_credibility": "execution",
    "drive_and_ambition": "ambition",
    "adaptability": "learnability",
}

_MAX_PROJECTS = 6


def _normalize_end_date(to_date: Optional[str]) -> Optional[str]:
    if to_date is None:
        return None
    stripped = to_date.strip()
    if not stripped or stripped.lower() == "present":
        return None
    return stripped


_TRANSITION_TAG_MAP = {
    "promotion": ("promotion", "Promotion"),
    "transition": ("transition", "Stage transition"),
    "function_change": ("function", "Function change"),
}
"""extract's TimelineTransitionKind -> headhunt-G's JourneyTag. headhunt-G's
`kind` enum (JOURNEY_TAGS in profile.ts) is {promotion, transition, function,
pivot} and has no equivalent for "first_role" - a candidate's first job gets
no tag at all (`tag` is optional and there's nothing to badge)."""


def _journey_tag(transition: Optional[str]) -> Optional[dict]:
    mapped = _TRANSITION_TAG_MAP.get(transition)
    if mapped is None:
        return None
    kind, label = mapped
    return {"kind": kind, "label": label}


def map_experiences(timeline: CareerTimeline) -> List[dict]:
    """CareerTimeline's work entries -> candidateProfileSchema experiences[].

    CareerTimeline is already sorted oldest->newest (headhunt-G's expected
    sort_order), so no reversal is needed. `context` comes from the entry's
    `domain_changed`; `tag` from its `transition` via _journey_tag (see
    timeline_builder.py) - no LLM involved.
    """
    work_entries = [e for e in timeline.entries if e.kind != "education"]
    return [
        _drop_none(
            {
                "title": e.title or "Unknown role",
                "company": e.institution,
                "startDate": e.from_date,
                "endDate": _normalize_end_date(e.to_date),
                "description": e.description,
                "context": "Domain change" if e.domain_changed else None,
                "tag": _journey_tag(e.transition),
            }
        )
        for e in work_entries
    ]


def map_education(timeline: CareerTimeline) -> List[dict]:
    education_entries = [e for e in timeline.entries if e.kind == "education"]
    return [
        _drop_none(
            {
                "school": e.institution or "Unknown school",
                "degree": e.title,
                "field": None,  # no structured field-of-study source on Education
                "year": e.to_date or e.from_date,
            }
        )
        for e in education_entries
    ]


def _repo_tech(repo: Repository) -> List[str]:
    if repo.primary_language:
        return [repo.primary_language]
    return []


_MAX_SKILL_GROUP_ITEMS = 10

_SKILL_GROUP_LABELS = {
    SOURCE_LINKEDIN_SKILL: "Skills (LinkedIn)",
    SOURCE_RESUME: "Skills (Resume)",
    SOURCE_RESUME_PROJECT: "Project Technologies (Resume)",
    SOURCE_GITHUB_TECHNOLOGY: "Technologies (GitHub)",
}
_SKILL_GROUP_ORDER = [
    SOURCE_LINKEDIN_SKILL,
    SOURCE_RESUME,
    SOURCE_RESUME_PROJECT,
    SOURCE_GITHUB_TECHNOLOGY,
]


def map_skill_groups(
    github_summary: Optional[GitHubCandidateSummary],
    resume: Optional[ResumeData] = None,
    person: Optional[Person] = None,
) -> List[dict]:
    """skillGroups is derived from aggregate_skills(), which merges LinkedIn
    skills, resume Skills/Projects sections, and GitHub's top_technologies
    (deterministic, no LLM). One group per source, in priority order; a
    skill found via multiple sources appears in its first-matching group
    only. Empty if none of the three carry a skill signal."""
    entries = aggregate_skills(resume, github_summary, person)

    grouped: dict = {source: [] for source in _SKILL_GROUP_ORDER}
    for entry in entries:
        primary_source = next((s for s in _SKILL_GROUP_ORDER if s in entry.sources), None)
        if primary_source is not None:
            grouped[primary_source].append(entry.name)

    return [
        {"label": _SKILL_GROUP_LABELS[source], "skills": grouped[source][:_MAX_SKILL_GROUP_ITEMS]}
        for source in _SKILL_GROUP_ORDER
        if grouped[source]
    ]


def map_projects_from_github(
    github_result: Optional[GitHubAnalysisResult],
    github_summary: Optional[GitHubCandidateSummary] = None,
) -> List[dict]:
    """GitHub projects not already mentioned in the resume/LinkedIn come
    first (genuinely new information - see GitHubCandidateSummary.
    unlisted_projects), filled out with top-starred repos if there's room
    left under _MAX_PROJECTS. Tagged sourceType="github_repo"."""
    if github_result is None:
        return []

    repos_by_url = {r.url: r for r in github_result.repositories}
    projects: List[dict] = []
    seen_urls = set()

    if github_summary is not None:
        for up in github_summary.unlisted_projects[:_MAX_PROJECTS]:
            repo = repos_by_url.get(up.url)
            projects.append(
                {
                    "name": up.name,
                    "kind": "GitHub",
                    "summary": up.description or "GitHub repository.",
                    "tech": _repo_tech(repo) if repo else [],
                    "href": up.url,
                    "sourceType": "github_repo",
                }
            )
            seen_urls.add(up.url)

    if len(projects) < _MAX_PROJECTS:
        originals = [r for r in github_result.repositories if not r.is_fork and r.url not in seen_urls]
        top = sorted(originals, key=lambda r: r.stars, reverse=True)[: _MAX_PROJECTS - len(projects)]
        for r in top:
            projects.append(
                {
                    "name": r.name,
                    "kind": "GitHub",
                    "summary": r.description or f"GitHub repository ({r.primary_language or 'unspecified language'}).",
                    "tech": _repo_tech(r),
                    "href": r.url,
                    "sourceType": "github_repo",
                }
            )

    return projects


def _normalize_href(href: str) -> str:
    parsed = urlparse(href.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}".lower()


def _classify_url(href: str) -> str:
    host = urlparse(href).netloc.lower()
    if "github.com" in host:
        return "GitHub"
    if "linkedin.com" in host:
        return "LinkedIn"
    if "medium.com" in host:
        return "Medium"
    if any(h in host for h in ("arxiv.org", "scholar.google.com", "researchgate.net")):
        return "Research"
    return "Other"


def _label_for_url(href: str) -> str:
    parsed = urlparse(href)
    path = parsed.path.strip("/")
    return path.split("/")[-1] if path else parsed.netloc


def map_external_sources(
    person: Optional[Person],
    resume: Optional[ResumeData],
    github_summary: Optional[GitHubCandidateSummary] = None,
) -> List[dict]:
    """Union of resume links (github_url/linkedin_url/other_urls), the
    LinkedIn profile URL, and an unlisted GitHub-profile portfolio URL (if
    one was found and isn't already among the above) - deduped by
    normalized href."""
    candidate_hrefs: List[str] = []
    if resume is not None:
        if resume.github_url:
            candidate_hrefs.append(resume.github_url)
        if resume.linkedin_url:
            candidate_hrefs.append(resume.linkedin_url)
        candidate_hrefs.extend(resume.other_urls)
    if person is not None and person.linkedin_url:
        candidate_hrefs.append(person.linkedin_url)

    portfolio_href = github_summary.unlisted_portfolio_url if github_summary else None

    seen = set()
    sources = []
    for href in candidate_hrefs:
        if not href:
            continue
        key = _normalize_href(href)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            _drop_none(
                {
                    "category": _classify_url(href),
                    "label": _label_for_url(href),
                    "href": href,
                    "subtitle": None,
                    "sourceType": "resume_link",
                }
            )
        )

    if portfolio_href and _normalize_href(portfolio_href) not in seen:
        sources.append(
            _drop_none(
                {
                    "category": "Portfolio",
                    "label": _label_for_url(portfolio_href),
                    "href": portfolio_href,
                    "subtitle": "GitHub profile website",
                    # headhunt-G's SOURCE_TYPES enum (profile.ts) is only
                    # {github_repo, resume_link, manual} - "github_repo" is
                    # the closest fit for "discovered on the GitHub profile,
                    # not literally a repo" and still surfaces the intended
                    # "extracted from GitHub" provenance badge.
                    "sourceType": "github_repo",
                }
            )
        )
    return sources


def map_candidate_profile(
    person: Optional[Person],
    resume: Optional[ResumeData],
    github_result: Optional[GitHubAnalysisResult],
) -> dict:
    """Builds the candidateProfileSchema payload (experiences/education/
    skillGroups/projects/externalSources). Builds a CareerTimeline from
    `person` and a GitHubCandidateSummary from `github_result` internally
    (both deterministic, no LLM) to source tags/skills/projects."""
    name = person.name if person else None
    headline = person.job_title if person else None
    location = person.location if person else None
    summary = (person.about[:280] if person and person.about else None)
    timeline = build_career_timeline(person) if person else CareerTimeline()
    github_summary = (
        build_candidate_github_summary(github_result, person, resume) if github_result else None
    )

    return _drop_none(
        {
            "name": name,
            "headline": headline,
            "location": location,
            "summary": summary,
            "narrative": None,
            "totalYearsExperience": timeline.total_years_experience,
            "experiences": map_experiences(timeline),
            "education": map_education(timeline),
            "skillGroups": map_skill_groups(github_summary, resume, person),
            "projects": map_projects_from_github(github_result, github_summary),
            "externalSources": map_external_sources(person, resume, github_summary),
        }
    )


def map_raw_text(person: Optional[Person], resume: Optional[ResumeData]) -> str:
    """candidates.raw_text is NOT NULL - must never be empty."""
    if resume is not None and resume.raw_text and resume.raw_text.strip():
        return resume.raw_text

    fallback_parts = []
    if person is not None:
        if person.about:
            fallback_parts.append(person.about)
        for e in person.experiences:
            fallback_parts.append(
                f"{e.position_title or ''} at {e.institution_name or ''} "
                f"({e.from_date or '?'} - {e.to_date or '?'}): {e.description or ''}"
            )
        for ed in person.educations:
            fallback_parts.append(f"{ed.degree or ''} at {ed.institution_name or ''}")

    fallback = "\n".join(p for p in fallback_parts if p.strip())
    if not fallback.strip():
        raise ValueError(
            "Cannot build raw_text: both ResumeData.raw_text and Person "
            "fallback content are empty."
        )
    return fallback


def map_evaluation_result(evaluation: StartupReadinessEvaluation) -> dict:
    """StartupReadinessEvaluation -> evaluationResultSchema payload."""
    dims = evaluation.dimensions
    readiness = []
    for extract_key, target_key in _DIMENSION_RENAME.items():
        dim = getattr(dims, extract_key)
        readiness.append(
            {
                "dimension": target_key,
                "score": dim.score,
                "summary": dim.assessment,
                "evidence": dim.evidence_basis,
            }
        )
    return {
        "overallScore": evaluation.overall_score,
        "recommendation": evaluation.recommendation,
        "readiness": readiness,
    }


def build_headhunt_payload(
    person: Optional[Person],
    resume: Optional[ResumeData],
    github_result: Optional[GitHubAnalysisResult],
    evaluation: StartupReadinessEvaluation,
    model: str,
) -> dict:
    """Full contract payload: {candidateProfile, evaluationResult, model, rawText}."""
    candidate_profile = map_candidate_profile(person, resume, github_result)
    if evaluation.candidate_narrative:
        candidate_profile["narrative"] = evaluation.candidate_narrative
    return {
        "candidateProfile": candidate_profile,
        "evaluationResult": map_evaluation_result(evaluation),
        "model": model,
        "rawText": map_raw_text(person, resume),
    }
