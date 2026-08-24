"""Chat-facing wrapper around the existing linkedin_scraper.crew sourcing crew.

linkedin_scraper/crew/ already implements the LinkedIn Searcher + Google
Searcher + Authority Reviewer architecture (agents.py, tasks.py, crew.py,
tools/) - this module does not rebuild any of that. It only adapts
run_sourcing_crew()'s output (an AuthorityReview: shortlist/maybe/rejected
with per-candidate rationale) into the same PersonSearchResult/outcome shape
sourcing/pipeline.py's XraySearchOutcome uses, so the frontend's existing
JobProgress/CandidateTable components render crew results without any
crew-specific UI code, and so the crew's shortlist gets an Excel/JSON export
via the same export_candidates_to_excel used everywhere else in this app.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from linkedin_scraper.export import export_candidates_to_excel
from linkedin_scraper.llm.base import LLMError
from linkedin_scraper.models.jd_signals import JDSignals
from linkedin_scraper.models.person_search import PersonSearchResult
from linkedin_scraper.sourcing import extract_jd_signals, jd_signals_from_flags


class CrewSearchOutcome(BaseModel):
    signals: JDSignals
    collected_count: int
    after_score_count: int
    after_years_count: int
    candidates: List[PersonSearchResult]  # the authority agent's shortlist
    excel_path: str
    json_path: str
    enriched: List[dict] = Field(default_factory=list)
    # Crew-specific extras, not present on XraySearchOutcome - available to
    # the chat layer for its text response, ignored by the generic table UI.
    maybe: List[PersonSearchResult] = Field(default_factory=list)
    rejected_count: int = 0
    summary: str = ""
    linkedin_count: int = 0
    google_count: int = 0
    overlap_count: int = 0


def _verdict_to_candidate(verdict: Dict[str, Any]) -> PersonSearchResult:
    sources = verdict.get("sources") or []
    indicators = [f"sources: {', '.join(sources)}"] if sources else []
    if verdict.get("rationale"):
        indicators.append(verdict["rationale"])
    return PersonSearchResult(
        name=verdict["name"],
        linkedin_url=verdict["linkedin_url"],
        headline=verdict.get("headline"),
        location=verdict.get("location"),
        fit_score=verdict.get("fit_score", 0),
        fit_indicators=indicators,
    )


async def _resolve_signals(
    jd_text: Optional[str],
    titles: Optional[List[str]],
    must_have_skills: Optional[List[str]],
    nice_to_have_skills: Optional[List[str]],
    seniority: Optional[str],
    locations: Optional[List[str]],
    min_years: Optional[int],
    max_years: Optional[int],
) -> JDSignals:
    if titles or must_have_skills:
        return jd_signals_from_flags(
            titles=titles or [],
            must_have_skills=must_have_skills or [],
            nice_to_have_skills=nice_to_have_skills or [],
            seniority=seniority,
            min_years=min_years,
            max_years=max_years,
            locations=locations or [],
            raw_jd_text=jd_text,
        )
    if jd_text:
        try:
            return await extract_jd_signals(jd_text)
        except LLMError:
            pass
    raise ValueError(
        "Need jd_text or titles/must_have_skills to run a candidate search - "
        "ask the user for these before calling this tool."
    )


async def run_candidate_search_crew(
    *,
    jd_text: Optional[str] = None,
    titles: Optional[List[str]] = None,
    must_have_skills: Optional[List[str]] = None,
    nice_to_have_skills: Optional[List[str]] = None,
    seniority: Optional[str] = None,
    locations: Optional[List[str]] = None,
    min_years: Optional[int] = None,
    max_years: Optional[int] = None,
    process: str = "sequential",
    session_path: str = "linkedin_session.json",
    shortlist_size: int = 15,
) -> CrewSearchOutcome:
    """Run the LinkedIn+Google searcher crew, reviewed by the authority agent.

    kickoff() is a blocking, multi-LLM-call method, so it runs in a worker
    thread (asyncio.to_thread) rather than blocking the event loop - same
    off-loop treatment every other long-running operation in this app gets.
    """
    from linkedin_scraper.crew import run_sourcing_crew

    signals = await _resolve_signals(
        jd_text, titles, must_have_skills, nice_to_have_skills, seniority, locations, min_years, max_years
    )

    skip_linkedin = not Path(session_path).exists()

    result = await asyncio.to_thread(
        run_sourcing_crew,
        signals,
        process=process,
        session_path=session_path,
        skip_linkedin=skip_linkedin,
        shortlist_size=shortlist_size,
    )

    review = result["review"]
    shortlist = [_verdict_to_candidate(v) for v in review.get("shortlist", [])]
    maybe = [_verdict_to_candidate(v) for v in review.get("maybe", [])]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = f"candidates/crew_{timestamp}.xlsx"
    excel_path = export_candidates_to_excel(shortlist, output_path)

    json_path = Path(output_path).with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return CrewSearchOutcome(
        signals=signals,
        collected_count=review.get("linkedin_count", 0) + review.get("google_count", 0),
        after_score_count=len(shortlist) + len(maybe),
        after_years_count=len(shortlist),
        candidates=shortlist,
        excel_path=str(excel_path),
        json_path=str(json_path),
        maybe=maybe,
        rejected_count=review.get("rejected_count", 0),
        summary=review.get("summary", ""),
        linkedin_count=review.get("linkedin_count", 0),
        google_count=review.get("google_count", 0),
        overlap_count=review.get("overlap_count", 0),
    )
