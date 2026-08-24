"""CrewAI agent definitions for dual-source candidate sourcing."""

from __future__ import annotations

from typing import Any, List, Optional

from ..models.jd_signals import JDSignals


def _require_crewai():
    try:
        from crewai import Agent, LLM
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "CrewAI is required for linkedin_scraper.crew. "
            'Install with: pip install -e ".[crew]"'
        ) from exc
    return Agent, LLM


def build_llm(model: Optional[str] = None) -> Any:
    """CrewAI LLM wrapper defaulting to Anthropic (matches the rest of this repo)."""
    _, LLM = _require_crewai()
    # litellm-style model id; ANTHROPIC_API_KEY must be set in the environment.
    return LLM(model=model or "anthropic/claude-sonnet-4-5-20250929")


def build_linkedin_searcher(
    signals: JDSignals,
    *,
    session_path: str = "linkedin_session.json",
    llm: Optional[Any] = None,
    headless: bool = False,
) -> Any:
    from .tools.linkedin_search import LinkedInPeopleSearchTool

    Agent, _ = _require_crewai()
    tool = LinkedInPeopleSearchTool(
        signals=signals,
        session_path=session_path,
        headless=headless,
    )
    return Agent(
        role="LinkedIn Searcher",
        goal=(
            "Find strong LinkedIn profile candidates for the open role using "
            "LinkedIn's native people-search UI, covering the JD's titles, "
            "must-have skills, and locations."
        ),
        backstory=(
            "You are a specialist recruiter who lives in LinkedIn Recruiter-style "
            "boolean search. You write tight keyword queries, fan out across a few "
            "title/skill variants, and return only real /in/ profile hits. You never "
            "invent candidates. If the session is missing, you report that clearly "
            "instead of fabricating results."
        ),
        tools=[tool],
        llm=llm or build_llm(),
        verbose=True,
        allow_delegation=False,
    )


def build_google_searcher(
    signals: JDSignals,
    *,
    llm: Optional[Any] = None,
    skip_skills_in_query: bool = False,
) -> Any:
    from .tools.google_search import GoogleXraySearchTool

    Agent, _ = _require_crewai()
    tool = GoogleXraySearchTool(
        signals=signals,
        skip_skills_in_query=skip_skills_in_query,
    )
    return Agent(
        role="Google Searcher",
        goal=(
            "Discover LinkedIn profiles via Google X-ray search (site:linkedin.com/in/) "
            "that match the JD, maximizing recall beyond LinkedIn's own UI ranking."
        ),
        backstory=(
            "You are an OSINT-minded sourcer who builds Google X-ray boolean queries "
            "and runs them through a SERP API. You prefer several focused queries over "
            "one overloaded clause, and you return structured candidate lists only — "
            "never fabricated profiles."
        ),
        tools=[tool],
        llm=llm or build_llm(),
        verbose=True,
        allow_delegation=False,
    )


def build_authority_agent(*, llm: Optional[Any] = None) -> Any:
    """High-authority reviewer — manager over both searchers' lists and outputs."""
    Agent, _ = _require_crewai()
    return Agent(
        role="Authority Reviewer",
        goal=(
            "Review candidate lists from the LinkedIn Searcher and Google Searcher, "
            "deduplicate, reconcile disagreements, and produce a final shortlist with "
            "clear accept/maybe/reject rationale grounded in the JD."
        ),
        backstory=(
            "You are the hiring bar-raiser. Searchers cast a wide net; you decide who "
            "survives. You trust overlap across sources, penalize weak headline/JD fit, "
            "and never pad the shortlist to hit a quota. You cite concrete signals "
            "(title, skills, location, years) in every verdict."
        ),
        llm=llm or build_llm(),
        verbose=True,
        allow_delegation=True,
    )


def collect_search_tools(agents: List[Any]) -> List[Any]:
    """Return tool instances attached to searcher agents (for post-run result access)."""
    tools: List[Any] = []
    for agent in agents:
        for tool in getattr(agent, "tools", None) or []:
            tools.append(tool)
    return tools
