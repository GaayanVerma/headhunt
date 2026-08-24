#!/usr/bin/env python3
"""
Search LinkedIn for Founding Engineer candidates and export to Excel.

Tailored for a Founding Engineer, Bangalore (in-office) JD: 2-5 YOE, backend-
heavy full stack, AI-powered backend systems / unstructured data pipelines,
comfort with AI tools, high ownership / 0->1 startup experience. Candidates
are required to come from a tier-1 Indian engineering college.

There is no seed set of "ideal fit" reference profiles for this specific role
(unlike samples/search_fullstack_dhrupra.py), so search queries are built
directly from JD signals instead of derived from scraped reference profiles.

College requirement: rather than bundling all tier-1 colleges into one boolean
OR clause appended to every query (samples/search_fullstack_dhrupra.py's
--colleges flag does this, but that script's own build_reference_searches()
comment records that pattern returning 0 results every time in live testing),
this script emits one query PER college, each paired with a JD anchor term
(e.g. "IIT founding engineer"). That's the "one query per term" pattern the
Dhrupra script had to adopt for its school/company/skill loops after the same
OR-bundling failure - so every result here comes from a query that already
required a tier-1 college mention, making the requirement a search-time
guarantee rather than a post-hoc filter.

Prerequisites:
    1. Create a LinkedIn session:
         python samples/create_session.py
    2. Install Excel export dependency:
         pip install openpyxl

Usage:
    python samples/search_founding_engineer_bangalore.py
    python samples/search_founding_engineer_bangalore.py --limit 300 --output candidates/founding_engineer.xlsx
    python samples/search_founding_engineer_bangalore.py --min-score 20
    python samples/search_founding_engineer_bangalore.py --colleges "IIT,BITS"
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from linkedin_scraper import BrowserManager, ConsoleCallback
from linkedin_scraper.export import export_candidates_to_excel
from linkedin_scraper.models.person_search import PersonSearchResult
from linkedin_scraper.scrapers.people_search import PeopleSearchScraper

# Tier-1 Indian engineering colleges (consensus definition: IITs, top NITs,
# IIITs, BITS Pilani campuses, IISc, plus well-regarded state institutes).
# Short/abbreviated forms are used since they match how LinkedIn profile text
# (education entries) actually renders institute names.
DEFAULT_TIER1_COLLEGES = [
    "IIT", "NIT", "IIIT", "BITS", "IISc",
    "DTU", "NSUT", "Jadavpur", "COEP", "VJTI",
]

# Paired with each college to form "known good" simple 2-3 word AND queries
# (see module docstring for why colleges aren't bundled into one OR clause).
ANCHOR_TERMS = ["founding engineer", "backend engineer", "startup"]

# Used only when --colleges is passed empty, so the script still works with
# the tier-1 college requirement disabled.
FALLBACK_SEARCHES: List[Dict[str, str]] = [
    {"keywords": "founding engineer backend"},
    {"keywords": "backend engineer python node"},
    {"keywords": "backend engineer system design"},
    {"keywords": "startup 0 to 1 backend engineer"},
    {"keywords": "software engineer ai agent llm"},
]

# Weighted keyword groups for the Founding Engineer, Bangalore JD.
JD_SIGNALS: Dict[str, Tuple[int, List[str]]] = {
    "founding_ownership": (
        20,
        [
            "founding engineer", "founding", "first engineer", "employee #",
            "early engineer", "co-founder", "cofounder", "founder",
        ],
    ),
    "startup_0to1": (
        15,
        [
            "startup", "0 to 1", "0-1", "early stage", "seed stage",
            "series a", "founding team", "built from scratch",
        ],
    ),
    "backend_heavy": (
        15,
        [
            "backend engineer", "backend developer", "back-end",
            "server-side", "api development", "microservices",
        ],
    ),
    "architecture_scale": (
        10,
        [
            "system design", "architecture", "scalable", "scalability",
            "distributed systems", "high availability",
        ],
    ),
    "fullstack": (8, ["full stack", "fullstack", "full-stack"]),
    "backend_stack": (
        10,
        [
            "node.js", "nodejs", "python", "django", "flask", "java",
            "golang", "go ", "spring", "postgres", "postgresql", "redis",
            "kafka", "docker", "kubernetes",
        ],
    ),
    "ai_tools_fluency": (
        8,
        ["copilot", "cursor", "chatgpt", "claude", "ai-assisted", "ai tools"],
    ),
    "ai_agents_llm": (
        10,
        ["llm", "genai", "generative ai", "ai agent", "ai engineer", "machine learning"],
    ),
    "data_pipelines": (
        8,
        [
            "data pipeline", "etl", "data engineering", "unstructured data",
            "nlp", "document processing",
        ],
    ),
}

# JD experience band is 2-5 years; these phrasings show up in headlines for that band.
EXPERIENCE_BAND_TERMS = [
    "2 year", "3 year", "4 year", "5 year", "2-5 year", "2+ year", "3+ year",
]

BANGALORE_LOCATIONS = ["bengaluru", "bangalore", "karnataka"]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _sanitize_boolean_term(term: str) -> str:
    """
    Clean a college name before folding it into a query.

    Strips parenthetical suffixes (e.g. "IIT (Bombay)" -> "IIT") and quotes
    multi-word phrases so LinkedIn's parser treats them as one phrase instead
    of implicitly ANDing each word.
    """
    cleaned = re.sub(r"\s*\([^)]*\)", "", term).strip()
    if not cleaned:
        return ""
    return f'"{cleaned}"' if " " in cleaned else cleaned


def build_college_searches(colleges: List[str]) -> List[Dict[str, str]]:
    """One query per tier-1 college, paired with each JD anchor term."""
    searches: List[Dict[str, str]] = []
    for college in colleges:
        term = _sanitize_boolean_term(college)
        if not term:
            continue
        for anchor in ANCHOR_TERMS:
            searches.append({"keywords": f"{term} {anchor}"})
    return searches


def score_candidate_for_jd(candidate: PersonSearchResult) -> PersonSearchResult:
    """
    Score a search result against the Founding Engineer, Bangalore JD.

    Mutates and returns the candidate with fit_score and fit_indicators set.
    """
    haystack = _normalize(
        " ".join(
            part
            for part in (candidate.name, candidate.headline, candidate.location)
            if part
        )
    )

    score = 0
    indicators: List[str] = []

    for label, (weight, keywords) in JD_SIGNALS.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            score += weight
            indicators.append(label.replace("_", " "))

    if any(loc in haystack for loc in BANGALORE_LOCATIONS):
        score += 10
        indicators.append("bangalore location")

    if any(term in haystack for term in EXPERIENCE_BAND_TERMS):
        score += 5
        indicators.append("2-5 yoe signal")

    if candidate.connection_degree in {"1st", "2nd"}:
        score += 3
        indicators.append(f"{candidate.connection_degree} connection")

    candidate.fit_score = score
    candidate.fit_indicators = indicators
    return candidate


def rank_candidates(candidates: List[PersonSearchResult]) -> List[PersonSearchResult]:
    """Score and sort candidates by fit (descending), then name."""
    scored = [score_candidate_for_jd(candidate) for candidate in candidates]
    return sorted(scored, key=lambda c: (-c.fit_score, c.name.lower()))


async def run_searches(
    browser: BrowserManager,
    searches: List[Dict[str, str]],
    per_query_limit: int,
    max_pages: int,
    query_delay: float,
) -> List[PersonSearchResult]:
    """Run all search queries (on an already-open, session-loaded browser) and return deduplicated results."""
    all_results: Dict[str, PersonSearchResult] = {}

    scraper = PeopleSearchScraper(browser.page, ConsoleCallback())

    for index, query in enumerate(searches, start=1):
        keywords = query.get("keywords")
        location = query.get("location")
        label = " | ".join(part for part in (keywords, location) if part)

        print(f"\n[{index}/{len(searches)}] Searching: {label}")
        results: List[PersonSearchResult] = []
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                results = await scraper.search(
                    keywords=keywords,
                    location=location,
                    limit=per_query_limit,
                    max_pages=max_pages,
                    page_delay=2.0,
                )
                break
            except Exception as exc:
                if attempt < max_attempts:
                    # Transient network blips (e.g. ERR_NAME_NOT_RESOLVED) have
                    # been observed to sink an otherwise-successful run - a
                    # short backoff and retry rides through those instead of
                    # losing this query's results entirely.
                    wait_time = 5.0 * attempt
                    print(f"  Search failed (attempt {attempt}/{max_attempts}): {exc}. Retrying in {wait_time:.0f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"  Search failed after {max_attempts} attempts: {exc}")

        new_count = 0
        for result in results:
            if result.linkedin_url not in all_results:
                all_results[result.linkedin_url] = result
                new_count += 1

        print(f"  Found {len(results)} profiles ({new_count} new, {len(all_results)} total unique)")

        if index < len(searches):
            await asyncio.sleep(query_delay)

    return list(all_results.values())


_YEARS_PATTERN = re.compile(r"(\d{1,2})\s*\+?\s*(?:yrs?|years?|yoe)\b", re.IGNORECASE)


def _extract_max_years(text: str) -> Optional[int]:
    """Pull the largest years-of-experience number mentioned in text, if any."""
    matches = [int(m) for m in _YEARS_PATTERN.findall(text or "")]
    return max(matches) if matches else None


def passes_years_filter(
    candidate: PersonSearchResult,
    min_years: Optional[int],
    max_years: Optional[int],
) -> bool:
    """
    Keep candidates whose stated YOE (if any) falls within [min_years, max_years].

    LinkedIn search cards don't always state years of experience explicitly, so
    candidates with no YOE mention are kept (unknown, not excluded) rather than
    dropped outright.
    """
    if min_years is None and max_years is None:
        return True
    found = _extract_max_years(candidate.headline or "")
    if found is None:
        return True
    if max_years is not None and found > max_years:
        return False
    if min_years is not None and found < min_years:
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search LinkedIn for Founding Engineer candidates and export to Excel"
    )
    parser.add_argument(
        "--session",
        default="linkedin_session.json",
        help="Path to LinkedIn session file (default: linkedin_session.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=300,
        help="Target number of unique candidates to collect (default: 300)",
    )
    parser.add_argument(
        "--per-query",
        type=int,
        default=40,
        help="Max profiles per search query (default: 40)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=8,
        help="Max result pages per query (default: 8)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=15,
        help="Minimum JD fit score to include in export (default: 15)",
    )
    parser.add_argument(
        "--query-delay",
        type=float,
        default=4.0,
        help="Seconds to wait between search queries (default: 4)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output Excel path (default: candidates/founding_engineer_bangalore_<date>.xlsx)",
    )
    parser.add_argument(
        "--min-years",
        type=int,
        default=2,
        help="Min years of experience, parsed from headline text (e.g. '3+ YOE'). "
        "Candidates with no YOE mention are kept. Not a native LinkedIn filter. "
        "Default 2, matching the JD's 2-5 YOE band. Pass 0 to disable.",
    )
    parser.add_argument(
        "--max-years",
        type=int,
        default=5,
        help="Max years of experience, parsed from headline text (e.g. '3+ YOE'). "
        "Candidates with no YOE mention are kept. Not a native LinkedIn filter. "
        "Default 5, matching the JD's 2-5 YOE band. Pass a large value to disable.",
    )
    parser.add_argument(
        "--colleges",
        default=",".join(DEFAULT_TIER1_COLLEGES),
        help="Comma-separated tier-1 college names/abbreviations. One search query is "
        "issued per college (paired with each JD anchor term), so every result comes "
        "from a query that already required a college mention in full profile text "
        "(including education), not just the search card. "
        f"Default: {', '.join(DEFAULT_TIER1_COLLEGES)}. Pass an empty string to disable "
        "the tier-1 college requirement and fall back to plain JD-keyword queries.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    session_path = Path(args.session)
    if not session_path.exists():
        print(f"LinkedIn session not found: {session_path}")
        print("Run: python samples/create_session.py")
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = args.output or f"candidates/founding_engineer_bangalore_{timestamp}.xlsx"

    colleges = [c.strip() for c in args.colleges.split(",") if c.strip()]
    searches = build_college_searches(colleges) if colleges else list(FALLBACK_SEARCHES)

    print("=" * 60)
    print("Founding Engineer, Bangalore — LinkedIn Candidate Search")
    print("=" * 60)
    print(f"Target candidates: {args.limit}")
    if colleges:
        print(f"Tier-1 colleges: {', '.join(colleges)}")
    else:
        print("Tier-1 college requirement: disabled (using fallback JD-keyword queries)")
    print(f"Search queries: {len(searches)}")
    for query in searches:
        print(f"  - {query['keywords']}")
    print(f"Output: {output_path}")
    print("=" * 60)

    async with BrowserManager(headless=False) as browser:
        await browser.load_session(str(session_path))
        print("Session loaded")

        raw_candidates = await run_searches(
            browser=browser,
            searches=searches,
            per_query_limit=args.per_query,
            max_pages=args.max_pages,
            query_delay=args.query_delay,
        )

    ranked = rank_candidates(raw_candidates)
    filtered = [c for c in ranked if c.fit_score >= args.min_score]
    after_score = len(filtered)

    filtered = [c for c in filtered if passes_years_filter(c, args.min_years, args.max_years)]
    after_years = len(filtered)

    final = filtered[: args.limit]

    print("\n" + "=" * 60)
    print(f"Collected: {len(raw_candidates)} unique profiles")
    print(f"After min-score filter ({args.min_score}+): {after_score}")
    print(
        f"After years filter ({args.min_years}-{args.max_years} YOE, unknown YOE kept): {after_years}"
    )
    print(f"Exporting top {len(final)} candidates")
    print("=" * 60)

    if not final:
        print("No candidates matched the score threshold. Try lowering --min-score.")
        return 1

    excel_path = export_candidates_to_excel(final, output_path)
    print(f"\nExcel saved: {excel_path}")

    json_path = Path(output_path).with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps([c.model_dump() for c in final], indent=2),
        encoding="utf-8",
    )
    print(f"JSON backup: {json_path}")

    print("\nTop 10 candidates:")
    for index, candidate in enumerate(final[:10], start=1):
        headline = (candidate.headline or "")[:70]
        print(f"  {index:2}. [{candidate.fit_score:3}] {candidate.name} — {headline}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
