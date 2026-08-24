"""Assemble and run the dual-searcher + authority-reviewer CrewAI crew."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from ..models.jd_signals import JDSignals
from .review import parse_authority_review

ProcessMode = Literal["sequential", "hierarchical"]


def _require_crew():
    try:
        from crewai import Crew, Process
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "CrewAI is required for linkedin_scraper.crew. "
            'Install with: pip install -e ".[crew]"'
        ) from exc
    return Crew, Process


def build_sourcing_crew(
    signals: JDSignals,
    *,
    process: ProcessMode = "sequential",
    session_path: str = "linkedin_session.json",
    skip_linkedin: bool = False,
    skip_skills_in_query: bool = False,
    shortlist_size: int = 15,
    model: Optional[str] = None,
    headless: bool = False,
    verbose: bool = True,
) -> Any:
    """Build a crew: LinkedIn Searcher + Google Searcher, reviewed by Authority.

    sequential (default): LinkedIn → Google → Authority review (context = both).
    hierarchical: Authority is manager_agent and delegates to the two searchers,
    then synthesizes the final shortlist.
    """
    from .agents import (
        build_authority_agent,
        build_google_searcher,
        build_linkedin_searcher,
        build_llm,
    )
    from .tasks import (
        build_authority_review_task,
        build_google_search_task,
        build_linkedin_search_task,
    )

    Crew, Process = _require_crew()
    llm = build_llm(model)

    google_agent = build_google_searcher(
        signals, llm=llm, skip_skills_in_query=skip_skills_in_query
    )
    agents = [google_agent]
    google_task = build_google_search_task(google_agent, signals)
    tasks = [google_task]
    linkedin_task = None

    if not skip_linkedin:
        linkedin_agent = build_linkedin_searcher(
            signals, session_path=session_path, llm=llm, headless=headless
        )
        agents.insert(0, linkedin_agent)
        linkedin_task = build_linkedin_search_task(linkedin_agent, signals)
        tasks.insert(0, linkedin_task)

    authority = build_authority_agent(llm=llm)
    use_manager = process == "hierarchical"
    review_task = build_authority_review_task(
        authority,
        signals,
        linkedin_task=linkedin_task,
        google_task=google_task,
        shortlist_size=shortlist_size,
        assign_agent=not use_manager,
    )

    if use_manager:
        # Workers = searchers only. Authority is manager: delegates search, then
        # owns the review task (do not also list authority as a worker).
        return Crew(
            agents=agents,
            tasks=tasks + [review_task],
            process=Process.hierarchical,
            manager_agent=authority,
            verbose=verbose,
        )

    # Sequential: searchers run first; authority is a crew member (not manager)
    # and reviews via task context.
    return Crew(
        agents=agents + [authority],
        tasks=tasks + [review_task],
        process=Process.sequential,
        verbose=verbose,
    )


def run_sourcing_crew(
    signals: JDSignals,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Kick off the crew and return review + raw tool candidate lists."""
    from .agents import collect_search_tools

    crew = build_sourcing_crew(signals, **kwargs)
    result = crew.kickoff()
    review = parse_authority_review(result)

    tool_candidates: List[Dict[str, Any]] = []
    for tool in collect_search_tools(crew.agents):
        for candidate in getattr(tool, "last_results", []) or []:
            tool_candidates.append(candidate.model_dump())

    return {
        "review": review.model_dump(),
        "raw_output": str(result),
        "tool_candidates": tool_candidates,
    }
