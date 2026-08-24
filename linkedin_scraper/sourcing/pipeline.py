"""Reusable orchestrator for the X-ray JD candidate-search pipeline.

This is the single implementation of "run an X-ray search" - the CLI
(samples/search_xray_jd.py), the FastAPI backend, and the chat tool layer
all call run_xray_search() rather than each re-implementing the flow.

Unlike a CLI main(), every failure path here raises a PipelineError subclass
instead of printing + sys.exit/return, so non-CLI callers can catch and
handle it (e.g. surface it in a web response) rather than the process dying.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..callbacks import ProgressCallback
from ..core.browser import BrowserManager
from ..export import export_candidates_to_excel
from ..llm.base import LLMError
from ..models.jd_signals import JDSignals
from ..models.person_search import PersonSearchResult
from ..scrapers.person import PersonScraper
from .jd_parser import extract_jd_signals, jd_signals_from_flags
from .reference_profiles import (
    ReferenceSignal,
    build_similarity_signals,
    derive_reference_signal,
    load_or_scrape_reference_profiles,
)
from .scoring import passes_years_filter, rank_candidates, signals_from_jd
from .serp_client import SerperClient
from .xray import build_xray_queries, parse_xray_results


class PipelineError(Exception):
    """Base class for X-ray pipeline failures that a caller should handle."""


class SignalResolutionError(PipelineError):
    """Raised when JD signals cannot be resolved from either LLM or manual flags."""


class SessionRequiredError(PipelineError):
    """Raised when an operation needs a LinkedIn session file that isn't present."""


class XraySearchParams(BaseModel):
    """Mirrors every flag in samples/search_xray_jd.py's parse_args(), 1:1.

    This is the single schema shared by the CLI, the FastAPI request body, and
    the chat tool's input_schema, so every flag is guaranteed to be reachable
    from a UI/tool without hand-syncing three separate field lists.
    """

    jd_file: Optional[str] = None
    jd_text: Optional[str] = None
    no_llm: bool = False
    title: List[str] = Field(default_factory=list)
    must_have: List[str] = Field(default_factory=list)
    nice_to_have: List[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    location: List[str] = Field(default_factory=list)
    colleges: str = ""
    min_years: Optional[int] = None
    max_years: Optional[int] = None
    limit: int = 200
    min_score: int = 15
    max_queries: int = 20
    max_title_clauses: int = 4
    max_skill_clauses: int = 6
    no_skill_filter: bool = False
    results_per_query: int = 10
    pages_per_query: int = 1
    reference_profiles_file: Optional[str] = None
    reference_cache: str = "candidates/xray_reference_profiles_cache.json"
    refresh_references: bool = False
    enrich_top: int = 0
    session: str = "linkedin_session.json"
    output: str = ""


class EnrichedCandidate(BaseModel):
    name: str
    linkedin_url: str
    status: str  # "ok" | "error"
    person: Optional[dict] = None
    error: Optional[str] = None


class XraySearchOutcome(BaseModel):
    signals: JDSignals
    collected_count: int
    after_score_count: int
    after_years_count: int
    candidates: List[PersonSearchResult]
    excel_path: str
    json_path: str
    enriched: List[EnrichedCandidate] = Field(default_factory=list)


async def resolve_signals(params: XraySearchParams) -> JDSignals:
    """Resolve JD signals from LLM extraction or manual flags.

    Raises SignalResolutionError instead of exiting when neither path yields
    usable signals.
    """
    manual_flags_given = bool(
        params.title or params.must_have or params.nice_to_have or params.seniority or params.location
    )

    jd_text = None
    if params.jd_file:
        jd_text = Path(params.jd_file).read_text(encoding="utf-8")
    elif params.jd_text:
        jd_text = params.jd_text

    if not params.no_llm and jd_text and not manual_flags_given:
        try:
            return await extract_jd_signals(jd_text)
        except LLMError:
            pass  # fall through to manual flags below

    if not (params.title or params.must_have):
        raise SignalResolutionError(
            "No JD signals available: LLM extraction was skipped/failed and no "
            "title or must_have flags were given. Provide jd_file/jd_text with a "
            "valid ANTHROPIC_API_KEY, or pass title/must_have explicitly."
        )

    return jd_signals_from_flags(
        titles=params.title,
        must_have_skills=params.must_have,
        nice_to_have_skills=params.nice_to_have,
        seniority=params.seniority,
        min_years=params.min_years,
        max_years=params.max_years,
        locations=params.location,
        raw_jd_text=jd_text,
    )


async def run_discovery(
    signals: JDSignals,
    max_queries: int,
    results_per_query: int,
    reference_signal: Optional[ReferenceSignal],
    colleges: Optional[List[str]] = None,
    max_title_clauses: int = 4,
    max_skill_clauses: int = 6,
    skip_skills_in_query: bool = False,
    pages_per_query: int = 1,
    callback: Optional[ProgressCallback] = None,
) -> List[PersonSearchResult]:
    """Generate x-ray queries, run them through Serper.dev, and return deduped candidates.

    skip_skills_in_query drops must/nice-to-have skills from the AND-clause used to
    build queries (titles/location/colleges still apply) - useful when a JD's
    extracted "skills" are soft/abstract phrases (e.g. "Scalable Backend Design")
    that won't literally appear in a LinkedIn headline; ANDing them in would kill
    recall for no benefit. Scoring (elsewhere) still uses the full signals, so
    these terms still contribute as a soft ranking bonus when they do appear.
    """
    reference_terms = None
    if reference_signal is not None:
        reference_terms = {"titles": reference_signal.titles, "skills": reference_signal.skills}

    query_signals = signals
    if skip_skills_in_query:
        query_signals = signals.model_copy(update={"must_have_skills": [], "nice_to_have_skills": []})

    queries = build_xray_queries(
        query_signals,
        reference_terms=reference_terms,
        college_terms=colleges,
        max_queries=max_queries,
        max_title_clauses=max_title_clauses,
        max_skill_clauses=max_skill_clauses,
    )
    if not queries:
        if callback:
            await callback.on_progress("No x-ray queries could be generated from the given JD signals.", 100)
        return []

    all_candidates: Dict[str, PersonSearchResult] = {}
    async with SerperClient() as client:
        for index, query in enumerate(queries, start=1):
            if callback:
                pct = int((index - 1) / len(queries) * 100)
                await callback.on_progress(f"[{index}/{len(queries)}] Searching: {query}", pct)
            for page in range(1, pages_per_query + 1):
                try:
                    raw_results = await client.search(query, num=results_per_query, page=page)
                except Exception:
                    # Broad catch: retry_async already retries transient transport/timeout
                    # errors internally, but a query that still fails after exhausting
                    # those retries (or a non-transport SerpSearchError) shouldn't sink
                    # the whole run - log it and move on to the next page/query.
                    continue

                parsed = parse_xray_results(raw_results, query)
                new_count = 0
                for candidate in parsed:
                    if candidate.linkedin_url not in all_candidates:
                        all_candidates[candidate.linkedin_url] = candidate
                        new_count += 1

                if new_count == 0 and page > 1:
                    break

    return list(all_candidates.values())


async def enrich_top_candidates(
    session_path: Path,
    candidates: List[PersonSearchResult],
    count: int,
    callback: Optional[ProgressCallback] = None,
) -> List[EnrichedCandidate]:
    """Deep-scrape the top N candidates' full profiles via PersonScraper.

    Returns scraped data instead of writing files itself - callers that want
    the candidates/<name>/person.json convention call save_enriched_candidates()
    separately.
    """
    enriched: List[EnrichedCandidate] = []
    async with BrowserManager(headless=False) as browser:
        await browser.load_session(str(session_path))
        scraper = PersonScraper(browser.page, callback)

        for index, candidate in enumerate(candidates[:count], start=1):
            if callback:
                pct = int((index - 1) / count * 100)
                await callback.on_progress(f"[{index}/{count}] Enriching: {candidate.name}", pct)
            try:
                person = await scraper.scrape(candidate.linkedin_url)
            except Exception as exc:
                enriched.append(
                    EnrichedCandidate(
                        name=candidate.name,
                        linkedin_url=candidate.linkedin_url,
                        status="error",
                        error=str(exc),
                    )
                )
                continue

            enriched.append(
                EnrichedCandidate(
                    name=candidate.name,
                    linkedin_url=candidate.linkedin_url,
                    status="ok",
                    person=person.model_dump(),
                )
            )

    return enriched


def save_enriched_candidates(enriched: List[EnrichedCandidate], candidates_dir: str = "candidates") -> None:
    """Write candidates/<safe_name>/person.json for each successfully enriched candidate."""
    for item in enriched:
        if item.status != "ok" or item.person is None:
            continue
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in item.name).strip()
        out_dir = Path(candidates_dir) / safe_name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "person.json").write_text(
            json.dumps(item.person, indent=2, default=str), encoding="utf-8"
        )


async def run_xray_search(
    params: XraySearchParams,
    callback: Optional[ProgressCallback] = None,
) -> XraySearchOutcome:
    """Run the full X-ray JD candidate-search pipeline end to end.

    Signal resolution -> optional reference-profile scoring -> discovery ->
    ranking -> score/years filtering -> export -> optional enrichment.
    Raises SignalResolutionError / SessionRequiredError / SerpSearchError on
    failure instead of exiting - callers decide how to surface that.
    """
    if params.enrich_top > 0 and not Path(params.session).exists():
        raise SessionRequiredError(
            f"enrich_top requires a LinkedIn session, but {params.session} was not found. "
            "Run: python samples/create_session.py"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = params.output or f"candidates/xray_{timestamp}.xlsx"

    signals = await resolve_signals(params)
    if params.min_years is not None:
        signals.min_years = params.min_years
    if params.max_years is not None:
        signals.max_years = params.max_years

    reference_signal: Optional[ReferenceSignal] = None
    scoring_signals = signals_from_jd(signals)

    if params.reference_profiles_file:
        urls = [
            line.strip()
            for line in Path(params.reference_profiles_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not Path(params.session).exists():
            raise SessionRequiredError(
                f"reference_profiles_file requires a LinkedIn session, but {params.session} was not found."
            )
        async with BrowserManager(headless=False) as browser:
            await browser.load_session(params.session)
            reference_people = await load_or_scrape_reference_profiles(
                browser.page, urls, params.reference_cache, params.refresh_references
            )
        reference_signal = derive_reference_signal(reference_people)
        scoring_signals = {**scoring_signals, **build_similarity_signals(reference_signal)}

    colleges = [c.strip() for c in params.colleges.split(",") if c.strip()]

    raw_candidates = await run_discovery(
        signals=signals,
        max_queries=params.max_queries,
        results_per_query=params.results_per_query,
        reference_signal=reference_signal,
        colleges=colleges,
        max_title_clauses=params.max_title_clauses,
        max_skill_clauses=params.max_skill_clauses,
        skip_skills_in_query=params.no_skill_filter,
        pages_per_query=params.pages_per_query,
        callback=callback,
    )

    yoe_range = (signals.min_years, signals.max_years) if (signals.min_years or signals.max_years) else None
    ranked = rank_candidates(raw_candidates, scoring_signals, yoe_range=yoe_range)
    filtered = [c for c in ranked if c.fit_score >= params.min_score]
    after_score = len(filtered)

    filtered = [c for c in filtered if passes_years_filter(c, signals.min_years, signals.max_years)]
    after_years = len(filtered)

    final = filtered[: params.limit]

    excel_path = export_candidates_to_excel(final, output_path)

    json_path = Path(output_path).with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps([c.model_dump() for c in final], indent=2), encoding="utf-8")

    enriched: List[EnrichedCandidate] = []
    if params.enrich_top > 0 and final:
        enriched = await enrich_top_candidates(Path(params.session), final, params.enrich_top, callback=callback)
        save_enriched_candidates(enriched)

    return XraySearchOutcome(
        signals=signals,
        collected_count=len(raw_candidates),
        after_score_count=after_score,
        after_years_count=after_years,
        candidates=final,
        excel_path=str(excel_path),
        json_path=str(json_path),
        enriched=enriched,
    )
