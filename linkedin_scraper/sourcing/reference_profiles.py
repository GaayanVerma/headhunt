"""Reference-profile similarity scoring.

Given a handful of known-good-fit LinkedIn profiles for a role, derive what's
common across them (titles/skills/companies/schools) and turn that into a
scoring bonus - candidates who share a title cluster or company with the
reference set score higher, on top of plain JD keyword matching. This is the
"not just React AND IIT" signal: originally prototyped per-JD in
samples/search_fullstack_dhrupra.py, now the shared, reusable version.
"""

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.async_api import Page

from ..callbacks import ProgressCallback
from ..models.person import Person
from ..scrapers.person import PersonScraper


@dataclass
class ReferenceSignal:
    """Common titles/skills/companies/schools derived from a reference-profile set."""

    titles: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    companies: List[str] = field(default_factory=list)
    schools: List[str] = field(default_factory=list)


def derive_reference_signal(people: List[Person]) -> ReferenceSignal:
    """Aggregate titles/skills/companies/schools across scraped reference profiles."""
    title_counter: Counter = Counter()
    skill_counter: Counter = Counter()
    company_counter: Counter = Counter()
    school_counter: Counter = Counter()

    for person in people:
        if person.job_title:
            title_counter[person.job_title.strip()] += 1
        if person.company:
            company_counter[person.company.strip()] += 1
        for skill in person.skills:
            if skill and skill.strip():
                skill_counter[skill.strip()] += 1
        for edu in person.educations:
            if edu.institution_name and edu.institution_name.strip():
                school_counter[edu.institution_name.strip()] += 1

    return ReferenceSignal(
        titles=[title for title, _ in title_counter.most_common(6)],
        skills=[skill for skill, _ in skill_counter.most_common(20)],
        companies=[company for company, _ in company_counter.most_common(10)],
        schools=[school for school, _ in school_counter.most_common(10)],
    )


async def load_or_scrape_reference_profiles(
    page: Page,
    urls: List[str],
    cache_path: str,
    refresh: bool,
    callback: Optional[ProgressCallback] = None,
) -> List[Person]:
    """Load reference profiles from cache, or scrape them and populate the cache."""
    cache_file = Path(cache_path)

    if cache_file.exists() and not refresh:
        print(f"Loading cached reference profiles from {cache_file}")
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return [Person.model_validate(item) for item in data]

    scraper = PersonScraper(page, callback)
    people: List[Person] = []

    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] Scraping reference profile: {url}")
        try:
            person = await scraper.scrape(url)
            people.append(person)
        except Exception as exc:
            print(f"  Failed to scrape {url}: {exc}")

        if index < len(urls):
            await asyncio.sleep(2.0)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps([p.model_dump() for p in people], indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Cached {len(people)} reference profiles to {cache_file}")

    return people


def build_similarity_signals(signal: ReferenceSignal) -> Dict[str, Tuple[int, List[str]]]:
    """Weighted signal groups (same shape as scoring.JD_SIGNALS) rewarding similarity to a reference set."""
    similarity_signals: Dict[str, Tuple[int, List[str]]] = {}
    if signal.companies:
        similarity_signals["similar_company"] = (8, signal.companies)
    if signal.titles:
        similarity_signals["similar_title"] = (6, signal.titles)
    return similarity_signals
