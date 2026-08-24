"""CrewAI task definitions for dual-source sourcing + authority review."""

from __future__ import annotations

from typing import Any, Optional

from ..models.jd_signals import JDSignals


def _require_task():
    try:
        from crewai import Task
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "CrewAI is required for linkedin_scraper.crew. "
            'Install with: pip install -e ".[crew]"'
        ) from exc
    return Task


def _jd_brief(signals: JDSignals) -> str:
    return (
        f"Titles: {', '.join(signals.titles) or '(none)'}\n"
        f"Must-have skills: {', '.join(signals.must_have_skills) or '(none)'}\n"
        f"Nice-to-have skills: {', '.join(signals.nice_to_have_skills) or '(none)'}\n"
        f"Seniority: {signals.seniority or '(unspecified)'}\n"
        f"YOE band: {signals.min_years}-{signals.max_years}\n"
        f"Locations: {', '.join(signals.locations) or '(any)'}\n"
        f"Excluded terms: {', '.join(signals.excluded_terms) or '(none)'}"
    )


def build_linkedin_search_task(agent: Any, signals: JDSignals) -> Any:
    Task = _require_task()
    return Task(
        description=(
            "Search LinkedIn for candidates matching this JD.\n\n"
            f"{_jd_brief(signals)}\n\n"
            "Call linkedin_people_search with 2-4 focused keyword queries covering "
            "the main titles and must-have skills. Prefer the primary location(s). "
            "Return a single consolidated JSON list of unique candidates (by "
            "linkedin_url) with source='linkedin'. If the session is missing, say so "
            "and return an empty list — do not invent people."
        ),
        expected_output=(
            "A JSON array of candidate objects: name, linkedin_url, headline, "
            "location, fit_score, fit_indicators, source='linkedin'."
        ),
        agent=agent,
    )


def build_google_search_task(agent: Any, signals: JDSignals) -> Any:
    Task = _require_task()
    return Task(
        description=(
            "Discover candidates via Google X-ray search for this JD.\n\n"
            f"{_jd_brief(signals)}\n\n"
            "Call google_xray_search (optionally with a focus hint for a title cluster). "
            "Return a JSON list of unique candidates with source='google'. "
            "Do not invent profiles."
        ),
        expected_output=(
            "A JSON array of candidate objects: name, linkedin_url, headline, "
            "location, fit_score, fit_indicators, source='google'."
        ),
        agent=agent,
    )


def build_authority_review_task(
    agent: Any,
    signals: JDSignals,
    *,
    linkedin_task: Optional[Any] = None,
    google_task: Optional[Any] = None,
    shortlist_size: int = 15,
    assign_agent: bool = True,
) -> Any:
    Task = _require_task()
    context = [t for t in (linkedin_task, google_task) if t is not None]
    kwargs: dict = {
        "description": (
            "You are the high-authority reviewer. You receive the LinkedIn Searcher's "
            "and Google Searcher's candidate lists/outputs.\n\n"
            f"JD brief:\n{_jd_brief(signals)}\n\n"
            "Do the following:\n"
            "1. Parse both lists. Deduplicate by linkedin_url.\n"
            "2. Mark sources for each person (linkedin, google, or both).\n"
            "3. Prefer candidates found by BOTH sources when fit is comparable.\n"
            "4. Reject obvious mismatches (wrong function, excluded terms, wrong geo "
            "when location is hard, inflated titles with zero skill overlap).\n"
            f"5. Produce a shortlist of at most {shortlist_size} 'shortlist' candidates, "
            "a smaller 'maybe' bucket, and a rejected_count.\n"
            "6. Write a short summary of source coverage and hiring-bar rationale.\n\n"
            "Output valid JSON matching this shape:\n"
            "{\n"
            '  "shortlist": [{"name","linkedin_url","headline","location","sources",'
            '"fit_score","decision","rationale"}],\n'
            '  "maybe": [ ... same shape ... ],\n'
            '  "rejected_count": <int>,\n'
            '  "linkedin_count": <int>,\n'
            '  "google_count": <int>,\n'
            '  "overlap_count": <int>,\n'
            '  "summary": "<string>"\n'
            "}"
        ),
        "expected_output": (
            "JSON AuthorityReview with shortlist, maybe, counts, and summary. "
            "Every shortlist/maybe entry must include a concrete rationale."
        ),
        "context": context or None,
    }
    if assign_agent:
        kwargs["agent"] = agent
    return Task(**kwargs)
