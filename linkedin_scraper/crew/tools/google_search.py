"""Google X-ray search tool — Serper.dev site:linkedin.com/in/ discovery."""

from __future__ import annotations

import json
from typing import Dict, List, Type

from pydantic import BaseModel, Field

from ...models.jd_signals import JDSignals
from ...models.person_search import PersonSearchResult
from ...sourcing.scoring import passes_years_filter, score_candidate_for_jd, signals_from_jd
from ...sourcing.serp_client import SerperClient
from ...sourcing.xray import build_xray_queries, parse_xray_results
from ..async_utils import run_sync

try:
    from crewai.tools import BaseTool
except ImportError as _crewai_import_error:  # pragma: no cover - optional extra
    raise ImportError(
        "CrewAI is required for google_xray_search. "
        'Install with: pip install -e ".[crew]"'
    ) from _crewai_import_error


class GoogleXraySearchInput(BaseModel):
    """Inputs the Google searcher agent can pass when calling the tool."""

    focus: str = Field(
        default="",
        description=(
            "Optional focus hint (e.g. a title or skill cluster) to bias which "
            "X-ray queries run first. Leave empty to use the full JD signals."
        ),
    )
    max_queries: int = Field(
        default=4,
        ge=1,
        le=12,
        description="Max X-ray queries to run this call.",
    )
    results_per_query: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Serper results per query (free tier caps at 10).",
    )


class GoogleXraySearchTool(BaseTool):
    """Run Google X-ray (site:linkedin.com/in/) via Serper and return candidates JSON."""

    name: str = "google_xray_search"
    description: str = (
        "Search Google for LinkedIn profiles matching the job description using "
        "X-ray queries (site:linkedin.com/in/). Returns a JSON list of candidates "
        "with name, linkedin_url, headline, location, fit_score, and fit_indicators. "
        "Does not require a LinkedIn session."
    )
    args_schema: Type[BaseModel] = GoogleXraySearchInput

    signals: JDSignals
    skip_skills_in_query: bool = False
    last_results: List[PersonSearchResult] = Field(default_factory=list, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(
        self,
        focus: str = "",
        max_queries: int = 4,
        results_per_query: int = 10,
    ) -> str:
        results = run_sync(
            self._search(focus=focus, max_queries=max_queries, results_per_query=results_per_query)
        )
        self.last_results = results
        return json.dumps(
            [
                {
                    "source": "google",
                    "name": c.name,
                    "linkedin_url": c.linkedin_url,
                    "headline": c.headline,
                    "location": c.location,
                    "fit_score": c.fit_score,
                    "fit_indicators": c.fit_indicators,
                    "search_query": c.search_query,
                }
                for c in results
            ],
            indent=2,
        )

    async def _search(
        self,
        focus: str,
        max_queries: int,
        results_per_query: int,
    ) -> List[PersonSearchResult]:
        query_signals = self.signals
        if self.skip_skills_in_query:
            query_signals = self.signals.model_copy(
                update={"must_have_skills": [], "nice_to_have_skills": []}
            )

        reference_terms = None
        if focus.strip():
            # Bias title coverage toward the agent's focus hint without rewriting the JD.
            reference_terms = {"titles": [focus.strip()], "skills": []}

        queries = build_xray_queries(
            query_signals,
            reference_terms=reference_terms,
            max_queries=max_queries,
        )
        if not queries:
            return []

        score_signals = signals_from_jd(self.signals)
        by_url: Dict[str, PersonSearchResult] = {}

        async with SerperClient() as client:
            for query in queries:
                raw = await client.search(query, num=results_per_query)
                for candidate in parse_xray_results(raw, query):
                    if not passes_years_filter(
                        candidate, self.signals.min_years, self.signals.max_years
                    ):
                        continue
                    scored = score_candidate_for_jd(
                        candidate,
                        score_signals,
                        location_terms=self.signals.locations or None,
                    )
                    existing = by_url.get(scored.linkedin_url)
                    if existing is None or scored.fit_score > existing.fit_score:
                        by_url[scored.linkedin_url] = scored

        return sorted(by_url.values(), key=lambda c: (-c.fit_score, c.name.lower()))
