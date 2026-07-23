#!/usr/bin/env python3
"""
Search LinkedIn for full stack developer candidates and export to Excel.

Tailored for the Dhrupra Services Pvt. Ltd. Full Stack Developer JD (React 18 +
TypeScript, Node.js/Express, SQL + NoSQL, 1-3 YOE). Location is not filtered or
scored — candidates from anywhere are considered. Runs multiple LinkedIn people
searches, deduplicates, scores by JD fit, and writes a ranked Excel spreadsheet.

Prerequisites:
    1. Create a LinkedIn session:
         python samples/create_session.py
    2. Install Excel export dependency:
         pip install openpyxl

Usage:
    python samples/search_fullstack_dhrupra.py
    python samples/search_fullstack_dhrupra.py --limit 300 --output candidates/dhrupra_fullstack.xlsx
    python samples/search_fullstack_dhrupra.py --min-score 20
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

# Search queries tuned to the Dhrupra Services Full Stack Developer JD.
DEFAULT_SEARCHES = [
    {"keywords": "full stack developer react node"},
    {"keywords": "react developer typescript"},
    {"keywords": "node.js developer express"},
    {"keywords": "frontend developer react typescript"},
    {"keywords": "backend developer node express postgresql"},
    {"keywords": "full stack engineer react node mongodb"},
    {"keywords": "javascript developer react node express"},
    {"keywords": "software engineer react node sql"},
]

# Weighted keyword groups for the Dhrupra Services Full Stack Developer JD.
JD_SIGNALS: Dict[str, Tuple[int, List[str]]] = {
    "react_typescript": (
        15,
        [
            "react", "react.js", "reactjs", "react 18", "hooks", "typescript", "type script",
            "redux", "context api", "state management", "zustand",
        ],
    ),
    "node_express": (
        15,
        ["node.js", "nodejs", "node ", "express", "express.js", "rest api", "restful"],
    ),
    "sql_nosql": (
        10,
        ["postgresql", "postgres", "mysql", "sql", "mongodb", "nosql", "dynamodb"],
    ),
    "fullstack": (10, ["full stack", "fullstack", "full-stack"]),
    "html_css": (5, ["html5", "css3", "html", "css", "responsive design", "sass", "tailwind"]),
    "build_tooling": (5, ["vite", "esbuild", "modern build tooling"]),
    "testing": (5, ["jest", "react testing library", "testing library", "vitest", "cypress"]),
    "devops_basics": (5, ["docker", "ci/cd", "github actions", "jenkins"]),
    "git": (3, ["git", "github", "gitlab", "version control"]),
}

# JD experience band is 1-3 years; these phrasings show up in headlines for that band.
EXPERIENCE_BAND_TERMS = ["1-3 year", "1 to 3 year", "2 year", "3 year", "1+ year", "2+ year"]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def score_candidate_for_jd(candidate: PersonSearchResult) -> PersonSearchResult:
    """
    Score a search result against the Dhrupra full stack developer JD.

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

    if any(term in haystack for term in EXPERIENCE_BAND_TERMS):
        score += 5
        indicators.append("1-3 yoe signal")

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


def _with_college_boolean(keywords: Optional[str], colleges: List[str]) -> Optional[str]:
    """
    Append a boolean OR clause for colleges to a keyword string.

    LinkedIn's keyword search matches against a candidate's whole profile
    (including the education section), not just what's shown on the search
    card, so folding colleges in here filters at the search stage instead of
    guessing from headline text after the fact.
    """
    if not colleges:
        return keywords
    college_clause = "(" + " OR ".join(colleges) + ")"
    return f"{keywords} {college_clause}" if keywords else college_clause


async def run_searches(
    session_path: str,
    searches: List[Dict[str, str]],
    per_query_limit: int,
    max_pages: int,
    query_delay: float,
    colleges: Optional[List[str]] = None,
) -> List[PersonSearchResult]:
    """Run all search queries and return deduplicated results."""
    all_results: Dict[str, PersonSearchResult] = {}

    async with BrowserManager(headless=False) as browser:
        await browser.load_session(session_path)
        print("Session loaded")

        scraper = PeopleSearchScraper(browser.page, ConsoleCallback())

        for index, query in enumerate(searches, start=1):
            keywords = _with_college_boolean(query.get("keywords"), colleges or [])
            location = query.get("location")
            label = " | ".join(part for part in (keywords, location) if part)

            print(f"\n[{index}/{len(searches)}] Searching: {label}")
            try:
                results = await scraper.search(
                    keywords=keywords,
                    location=location,
                    limit=per_query_limit,
                    max_pages=max_pages,
                    page_delay=2.0,
                )
            except Exception as exc:
                print(f"  Search failed: {exc}")
                continue

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
        description="Search LinkedIn for full stack developer candidates and export to Excel"
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
        help="Output Excel path (default: candidates/dhrupra_fullstack_<date>.xlsx)",
    )
    parser.add_argument(
        "--min-years",
        type=int,
        default=1,
        help="Min years of experience, parsed from headline text (e.g. '3+ YOE'). "
        "Candidates with no YOE mention are kept. Not a native LinkedIn filter. "
        "Default 1, matching the JD's 1-3 YOE band. Pass 0 to disable.",
    )
    parser.add_argument(
        "--max-years",
        type=int,
        default=3,
        help="Max years of experience, parsed from headline text (e.g. '3+ YOE'). "
        "Candidates with no YOE mention are kept. Not a native LinkedIn filter. "
        "Default 3, matching the JD's 1-3 YOE band. Pass a large value to disable.",
    )
    parser.add_argument(
        "--colleges",
        default="",
        help="Comma-separated college names/abbreviations, ANDed as a boolean OR clause onto "
        "each search query (e.g. 'IIT,IIIT,NSIT,DTU,BITS' -> keywords + '(IIT OR IIIT OR ...)'). "
        "Matches LinkedIn's full profile text, including education, not just the search card.",
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
    output_path = args.output or f"candidates/dhrupra_fullstack_{timestamp}.xlsx"

    print("=" * 60)
    print("Dhrupra Services — Full Stack Developer LinkedIn Candidate Search")
    print("=" * 60)
    print(f"Target candidates: {args.limit}")
    print(f"Search queries: {len(DEFAULT_SEARCHES)}")
    print(f"Output: {output_path}")
    print("=" * 60)

    colleges = [c.strip() for c in args.colleges.split(",") if c.strip()]

    raw_candidates = await run_searches(
        session_path=str(session_path),
        searches=DEFAULT_SEARCHES,
        per_query_limit=args.per_query,
        max_pages=args.max_pages,
        query_delay=args.query_delay,
        colleges=colleges,
    )

    ranked = rank_candidates(raw_candidates)
    filtered = [c for c in ranked if c.fit_score >= args.min_score]
    after_score = len(filtered)

    filtered = [c for c in filtered if passes_years_filter(c, args.min_years, args.max_years)]
    after_years = len(filtered)

    final = filtered[: args.limit]

    print("\n" + "=" * 60)
    print(f"Collected: {len(raw_candidates)} unique profiles")
    if colleges:
        print(f"  (search-time college filter: {', '.join(colleges)})")
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
