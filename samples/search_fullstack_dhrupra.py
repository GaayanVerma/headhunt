#!/usr/bin/env python3
"""
Search LinkedIn for full stack developer candidates and export to Excel.

Tailored for the Dhrupra Services Pvt. Ltd. Full Stack Developer JD (React 18 +
TypeScript, Node.js/Express, SQL + NoSQL, 1-3 YOE). Location is not filtered or
scored — candidates from anywhere are considered.

Instead of generic keyword searches, this script is seeded from a set of
REFERENCE_PROFILES: real LinkedIn profiles that are a good match for the role.
It scrapes each reference profile once (caching the result), derives common
titles/skills/companies/schools across them, builds LinkedIn people-search
queries from that signal, and gives candidates a scoring bonus for sharing a
company or title cluster with the reference set — on top of the existing JD
keyword fit score.

Prerequisites:
    1. Create a LinkedIn session:
         python samples/create_session.py
    2. Install Excel export dependency:
         pip install openpyxl

Usage:
    python samples/search_fullstack_dhrupra.py
    python samples/search_fullstack_dhrupra.py --limit 300 --output candidates/dhrupra_fullstack.xlsx
    python samples/search_fullstack_dhrupra.py --min-score 20
    python samples/search_fullstack_dhrupra.py --refresh-references
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
from linkedin_scraper.sourcing.reference_profiles import (
    ReferenceSignal,
    build_similarity_signals,
    derive_reference_signal,
    load_or_scrape_reference_profiles,
)

# Real LinkedIn profiles that are a good match for the role. Search queries and
# scoring bonuses are derived from what's common across these profiles.
REFERENCE_PROFILES = [
    "https://www.linkedin.com/in/prateek-banga-324b64141/",
    "https://www.linkedin.com/in/parjanyamodi/",
    "https://www.linkedin.com/in/shreyas-dayal/",
    "https://www.linkedin.com/in/shreyashkgupta/",
    "https://www.linkedin.com/in/akshat-gupta-401675192/",
    "https://www.linkedin.com/in/avivashishta/",
    "https://www.linkedin.com/in/rathimanit/",
    "https://www.linkedin.com/in/teknicus/",
    "https://www.linkedin.com/in/msameermalik/",
]

DEFAULT_REFERENCE_CACHE = "candidates/reference_profiles_cache.json"

# Anchors the one broad, stack-precise search query to the JD's unchanged core stack.
CORE_STACK_TERMS = "react node typescript"

# Lighter single-term anchor for title/company/school/skill queries. AND-ing
# the full CORE_STACK_TERMS onto those already-narrow clauses repeatedly
# collapsed to 0 results live (LinkedIn's people-search index for the literal
# 3-way AND is small to begin with); a single anchor keeps queries scoped to
# the JD's #1 must-have without starving results.
ANCHOR_TERM = "react"

# Rotated across skill/company/school queries to grow the unique candidate
# pool - a "node X" query and a "react X" query for the same X return
# overlapping but non-identical result sets on LinkedIn's search.
EXTRA_ANCHOR_TERMS = ["react", "node"]

# Skills already implied by CORE_STACK_TERMS — excluded from the "extra skills"
# search query so it surfaces differentiating signal instead of repeating itself.
_CORE_SKILL_TERMS = {"react", "react.js", "reactjs", "node", "node.js", "nodejs", "typescript", "javascript", "js"}

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


def _with_boolean_clause(keywords: Optional[str], terms: List[str]) -> Optional[str]:
    """
    Append a boolean OR clause to a keyword string.

    LinkedIn's keyword search matches against a candidate's whole profile
    (including sections not shown on the search card), so folding terms in
    here filters at the search stage instead of guessing from headline text
    after the fact.
    """
    if not terms:
        return keywords
    sanitized = [_sanitize_boolean_term(t) for t in terms]
    sanitized = [t for t in sanitized if t]
    if not sanitized:
        return keywords
    clause = "(" + " OR ".join(sanitized) + ")"
    return f"{keywords} {clause}" if keywords else clause


def _sanitize_boolean_term(term: str) -> str:
    """
    Clean a term before folding it into a boolean OR clause.

    Strips parenthetical suffixes (e.g. "Clueso (YC W23)" -> "Clueso") which
    otherwise unbalance the outer "(...)" grouping, and quotes multi-word
    phrases (e.g. institution names) so LinkedIn's parser treats them as one
    phrase instead of implicitly ANDing each word.
    """
    cleaned = re.sub(r"\s*\([^)]*\)", "", term).strip()
    if not cleaned:
        return ""
    return f'"{cleaned}"' if " " in cleaned else cleaned


# Backwards-compatible alias — colleges are just one kind of boolean clause.
def _with_college_boolean(keywords: Optional[str], colleges: List[str]) -> Optional[str]:
    return _with_boolean_clause(keywords, colleges)


def build_reference_searches(signal: ReferenceSignal) -> List[Dict[str, str]]:
    """
    Build LinkedIn people-search queries from the reference-profile signal.

    Live testing (multiple runs today) showed a consistent pattern: a simple
    2-3 word AND query ("<title> react", "react IIT") reliably returns a
    couple of hits, but bundling a whole category into one boolean OR-clause
    ("react (Dock OR Clueso OR ...)") returned 0 results every time,
    regardless of anchor term, term count, or quoting - LinkedIn's basic
    people-search doesn't seem to handle multi-term OR-groups the way
    Recruiter/Sales Navigator's boolean search does. So instead of one query
    per category, this emits one query PER title/skill/company/school - more
    total queries, each using the "known good" simple-AND pattern, to
    maximize total unique candidates within LinkedIn's per-query cap.
    """
    searches: List[Dict[str, str]] = []

    # One broad query anchored on the full JD stack, mirroring the original
    # generic searches.
    searches.append({"keywords": CORE_STACK_TERMS})

    for title in signal.titles[:6]:
        searches.append({"keywords": f"{title} {ANCHOR_TERM}"})

    extra_skills = [
        skill for skill in signal.skills if skill.lower() not in _CORE_SKILL_TERMS
    ][:12]
    # Rotate through multiple anchors for skill/company/school terms - each
    # anchor surfaces a partly-different set of people (a "node X" query and
    # a "react X" query for the same X overlap but aren't identical), so this
    # meaningfully grows the unique pool beyond a single fixed anchor.
    for skill in extra_skills:
        term = _sanitize_boolean_term(skill)
        if term:
            for anchor in EXTRA_ANCHOR_TERMS:
                searches.append({"keywords": f"{anchor} {term}"})

    for company in signal.companies[:10]:
        term = _sanitize_boolean_term(company)
        if term:
            for anchor in EXTRA_ANCHOR_TERMS:
                searches.append({"keywords": f"{anchor} {term}"})

    for school in signal.schools[:10]:
        term = _sanitize_boolean_term(school)
        if term:
            for anchor in EXTRA_ANCHOR_TERMS:
                searches.append({"keywords": f"{anchor} {term}"})

    return searches


def score_candidate_for_jd(
    candidate: PersonSearchResult, signals: Dict[str, Tuple[int, List[str]]]
) -> PersonSearchResult:
    """
    Score a search result against the given weighted signal groups (JD signals
    plus any reference-profile similarity bonuses).

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

    for label, (weight, keywords) in signals.items():
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


def rank_candidates(
    candidates: List[PersonSearchResult], signals: Dict[str, Tuple[int, List[str]]]
) -> List[PersonSearchResult]:
    """Score and sort candidates by fit (descending), then name."""
    scored = [score_candidate_for_jd(candidate, signals) for candidate in candidates]
    return sorted(scored, key=lambda c: (-c.fit_score, c.name.lower()))


async def run_searches(
    browser: BrowserManager,
    searches: List[Dict[str, str]],
    per_query_limit: int,
    max_pages: int,
    query_delay: float,
    colleges: Optional[List[str]] = None,
) -> List[PersonSearchResult]:
    """Run all search queries (on an already-open, session-loaded browser) and return deduplicated results."""
    all_results: Dict[str, PersonSearchResult] = {}

    scraper = PeopleSearchScraper(browser.page, ConsoleCallback())

    for index, query in enumerate(searches, start=1):
        keywords = _with_boolean_clause(query.get("keywords"), colleges or [])
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
        "Matches LinkedIn's full profile text, including education, not just the search card. "
        "Applied on top of the reference-profile school clause, not instead of it.",
    )
    parser.add_argument(
        "--reference-cache",
        default=DEFAULT_REFERENCE_CACHE,
        help=f"Path to cache scraped reference-profile data (default: {DEFAULT_REFERENCE_CACHE})",
    )
    parser.add_argument(
        "--refresh-references",
        action="store_true",
        help="Re-scrape REFERENCE_PROFILES instead of using the cache",
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
    print(f"Reference profiles: {len(REFERENCE_PROFILES)}")
    print(f"Output: {output_path}")
    print("=" * 60)

    colleges = [c.strip() for c in args.colleges.split(",") if c.strip()]

    async with BrowserManager(headless=False) as browser:
        await browser.load_session(str(session_path))
        print("Session loaded")

        reference_people = await load_or_scrape_reference_profiles(
            browser.page,
            REFERENCE_PROFILES,
            args.reference_cache,
            args.refresh_references,
        )
        signal = derive_reference_signal(reference_people)
        searches = build_reference_searches(signal)
        signals = {**JD_SIGNALS, **build_similarity_signals(signal)}

        print(f"\nDerived {len(signal.titles)} titles, {len(signal.skills)} skills, "
              f"{len(signal.companies)} companies, {len(signal.schools)} schools from reference profiles")
        print(f"Search queries: {len(searches)}")
        for query in searches:
            print(f"  - {query['keywords']}")

        raw_candidates = await run_searches(
            browser=browser,
            searches=searches,
            per_query_limit=args.per_query,
            max_pages=args.max_pages,
            query_delay=args.query_delay,
            colleges=colleges,
        )

    ranked = rank_candidates(raw_candidates, signals)
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
