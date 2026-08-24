"""LinkedIn people-search tool — PeopleSearchScraper over a persisted session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Type

from pydantic import BaseModel, Field

from ...models.jd_signals import JDSignals
from ...models.person_search import PersonSearchResult
from ...sourcing.scoring import passes_years_filter, score_candidate_for_jd, signals_from_jd
from ..async_utils import run_sync

try:
    from crewai.tools import BaseTool
except ImportError as _crewai_import_error:  # pragma: no cover - optional extra
    raise ImportError(
        "CrewAI is required for linkedin_people_search. "
        'Install with: pip install -e ".[crew]"'
    ) from _crewai_import_error


class LinkedInPeopleSearchInput(BaseModel):
    """Inputs the LinkedIn searcher agent can pass when calling the tool."""

    keywords: str = Field(
        ...,
        description=(
            "Boolean-ish LinkedIn people-search keywords, e.g. "
            "'(\"Founding Engineer\" OR \"Staff Engineer\") TypeScript'."
        ),
    )
    location: str = Field(
        default="",
        description="Optional location filter (e.g. 'Bangalore', 'Gurgaon').",
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Max unique profiles to return for this query.",
    )


class LinkedInPeopleSearchTool(BaseTool):
    """Search LinkedIn's people-search UI via PeopleSearchScraper (needs session)."""

    name: str = "linkedin_people_search"
    description: str = (
        "Search LinkedIn's native people-search UI for profiles matching keywords "
        "and an optional location. Returns JSON candidates with name, linkedin_url, "
        "headline, location, fit_score, and fit_indicators. Requires a valid "
        "linkedin_session.json (create via samples/create_session.py). Prefer a few "
        "tight keyword queries over one giant OR clause."
    )
    args_schema: Type[BaseModel] = LinkedInPeopleSearchInput

    signals: JDSignals
    session_path: str = "linkedin_session.json"
    headless: bool = False
    max_pages: int = 3
    last_results: List[PersonSearchResult] = Field(default_factory=list, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, keywords: str, location: str = "", limit: int = 25) -> str:
        if not Path(self.session_path).exists():
            return json.dumps(
                {
                    "error": (
                        f"LinkedIn session file not found at {self.session_path}. "
                        "Run samples/create_session.py first, or rely on the Google "
                        "searcher agent alone."
                    ),
                    "candidates": [],
                }
            )

        results = run_sync(
            self._search(keywords=keywords, location=location or None, limit=limit)
        )
        self.last_results = results
        return json.dumps(
            [
                {
                    "source": "linkedin",
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
        keywords: str,
        location: Optional[str],
        limit: int,
    ) -> List[PersonSearchResult]:
        # Local imports keep Playwright off the critical path when the tool is unused.
        from linkedin_scraper import BrowserManager, ConsoleCallback
        from linkedin_scraper.scrapers.people_search import PeopleSearchScraper

        score_signals = signals_from_jd(self.signals)
        by_url: Dict[str, PersonSearchResult] = {}

        async with BrowserManager(headless=self.headless) as browser:
            await browser.load_session(self.session_path)
            scraper = PeopleSearchScraper(browser.page, ConsoleCallback())
            raw_results = await scraper.search(
                keywords=keywords,
                location=location,
                limit=limit,
                max_pages=self.max_pages,
            )

        for candidate in raw_results:
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
