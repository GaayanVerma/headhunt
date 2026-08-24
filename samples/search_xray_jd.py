#!/usr/bin/env python3
"""
Search for candidates matching a job description via Google X-ray search, and
export to Excel.

Unlike samples/search_fullstack_dhrupra.py / search_founding_engineer_bangalore.py,
this does NOT search LinkedIn's own people-search UI (rate-limited, checkpoint-
prone, requires a logged-in session for discovery). Instead it runs
site:linkedin.com/in/ boolean queries through Serper.dev (a real Google SERP
API - scraping Google's HTML directly gets blocked/CAPTCHA'd fast).

Flow: free-text JD -> JDSignals (LLM-extracted, or manual --flags if
ANTHROPIC_API_KEY is unavailable) -> X-ray queries -> Serper.dev search ->
parsed candidates -> scored (JD keyword fit + optional reference-profile
similarity bonus + YOE band) -> exported.

No LinkedIn session is needed for discovery. A session is only required for
--enrich-top (deep-scraping the top N candidates' full profiles via the
existing PersonScraper).

This is a thin CLI wrapper - the actual pipeline lives in
linkedin_scraper.sourcing.pipeline.run_xray_search(), which is also what the
web backend and the AI chat tool call, so there is exactly one implementation
of "run an X-ray search."

Prerequisites:
    1. Set SERPER_API_KEY in .env (see .env.example) - required, no fallback.
    2. Set ANTHROPIC_API_KEY in .env for LLM JD-signal extraction (optional -
       falls back to manual --title/--must-have/etc. flags without it).
    3. Install Excel export dependency: pip install openpyxl
    4. For --enrich-top: python samples/create_session.py

Usage:
    python samples/search_xray_jd.py --jd-file jd.txt
    python samples/search_xray_jd.py --jd-file jd.txt --min-score 15 --limit 200
    python samples/search_xray_jd.py --no-llm --title "Founding Engineer" --must-have TypeScript --must-have AWS --location Gurgaon
    python samples/search_xray_jd.py --jd-file jd.txt --enrich-top 5
"""
import argparse
import asyncio
import sys

from linkedin_scraper import ConsoleCallback
from linkedin_scraper.sourcing import (
    PipelineError,
    SessionRequiredError,
    SignalResolutionError,
    XraySearchParams,
    run_xray_search,
)
from linkedin_scraper.sourcing.serp_client import SerpSearchError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search for candidates matching a JD via Google X-ray search and export to Excel"
    )
    parser.add_argument("--jd-file", help="Path to a text file containing the job description")
    parser.add_argument("--jd-text", help="Job description text, passed directly")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM JD-signal extraction, use manual flags only")
    parser.add_argument("--title", action="append", default=[], help="Candidate title (repeatable)")
    parser.add_argument("--must-have", action="append", default=[], help="Must-have skill (repeatable)")
    parser.add_argument("--nice-to-have", action="append", default=[], help="Nice-to-have skill (repeatable)")
    parser.add_argument("--seniority", default=None, help="junior|mid|senior|staff+")
    parser.add_argument("--location", action="append", default=[], help="Location (repeatable)")
    parser.add_argument(
        "--colleges",
        default="",
        help="Comma-separated college names/abbreviations, ANDed as a boolean OR clause onto "
        "every query (e.g. 'IIT,NIT,BITS' -> ... (IIT OR NIT OR BITS)). Matches Google's index of "
        "the full profile page, including education entries.",
    )
    parser.add_argument("--min-years", type=int, default=None, help="Min years of experience")
    parser.add_argument("--max-years", type=int, default=None, help="Max years of experience")
    parser.add_argument("--limit", type=int, default=200, help="Target number of unique candidates (default: 200)")
    parser.add_argument("--min-score", type=int, default=15, help="Minimum JD fit score to include (default: 15)")
    parser.add_argument("--max-queries", type=int, default=20, help="Max x-ray queries to generate (default: 20)")
    parser.add_argument("--max-title-clauses", type=int, default=4, help="Titles per query OR-group before fanning out (default: 4)")
    parser.add_argument("--max-skill-clauses", type=int, default=6, help="Skills per query OR-group before fanning out (default: 6)")
    parser.add_argument(
        "--no-skill-filter",
        action="store_true",
        help="Don't AND must/nice-to-have skills into the search query (titles/location/colleges "
        "still apply) - use when a JD's skills are abstract/soft phrases unlikely to appear "
        "literally in a headline. Skills still contribute to scoring either way.",
    )
    parser.add_argument(
        "--results-per-query",
        type=int,
        default=10,
        help="Serper results per query (default: 10 - Serper.dev free-tier accounts reject "
        "num>10 with a 400 'Query pattern not allowed for free accounts' error; raise this if "
        "you're on a paid plan)",
    )
    parser.add_argument(
        "--pages-per-query",
        type=int,
        default=1,
        help="Google result pages to fetch per query (default: 1). Each page surfaces mostly-new "
        "profiles, so raising this is the main lever for reaching a large candidate count without "
        "generating many distinct queries. Stops early for a query once a page adds 0 new results.",
    )
    parser.add_argument("--reference-profiles-file", default=None, help="Path to newline-delimited reference LinkedIn URLs")
    parser.add_argument("--reference-cache", default="candidates/xray_reference_profiles_cache.json", help="Cache path for scraped reference profiles")
    parser.add_argument("--refresh-references", action="store_true", help="Re-scrape reference profiles instead of using the cache")
    parser.add_argument("--enrich-top", type=int, default=0, help="Deep-scrape the top N candidates via PersonScraper (0 = skip, default)")
    parser.add_argument("--session", default="linkedin_session.json", help="LinkedIn session file, only needed if --enrich-top > 0")
    parser.add_argument("--output", default="", help="Output Excel path (default: candidates/xray_<date>.xlsx)")
    return parser.parse_args()


def _params_from_args(args: argparse.Namespace) -> XraySearchParams:
    return XraySearchParams(
        jd_file=args.jd_file,
        jd_text=args.jd_text,
        no_llm=args.no_llm,
        title=args.title,
        must_have=args.must_have,
        nice_to_have=args.nice_to_have,
        seniority=args.seniority,
        location=args.location,
        colleges=args.colleges,
        min_years=args.min_years,
        max_years=args.max_years,
        limit=args.limit,
        min_score=args.min_score,
        max_queries=args.max_queries,
        max_title_clauses=args.max_title_clauses,
        max_skill_clauses=args.max_skill_clauses,
        no_skill_filter=args.no_skill_filter,
        results_per_query=args.results_per_query,
        pages_per_query=args.pages_per_query,
        reference_profiles_file=args.reference_profiles_file,
        reference_cache=args.reference_cache,
        refresh_references=args.refresh_references,
        enrich_top=args.enrich_top,
        session=args.session,
        output=args.output,
    )


async def main() -> int:
    args = parse_args()

    if not args.jd_file and not args.jd_text and not (args.title or args.must_have):
        print("Provide --jd-file, --jd-text, or manual --title/--must-have flags.")
        return 1

    params = _params_from_args(args)

    print("=" * 60)
    print("X-ray JD Candidate Search")
    print("=" * 60)

    try:
        outcome = await run_xray_search(params, callback=ConsoleCallback())
    except (SignalResolutionError, SessionRequiredError, SerpSearchError) as exc:
        print(f"{exc}")
        return 1
    except PipelineError as exc:
        print(f"Pipeline failed: {exc}")
        return 1

    signals = outcome.signals
    print(f"\nJD signals ({signals.extraction_source}):")
    print(f"  Titles: {signals.titles}")
    print(f"  Must-have skills: {signals.must_have_skills}")
    print(f"  Nice-to-have skills: {signals.nice_to_have_skills}")
    print(f"  Seniority: {signals.seniority}")
    print(f"  Locations: {signals.locations}")
    print(f"  YOE range: {signals.min_years}-{signals.max_years}")

    print("\n" + "=" * 60)
    print(f"Collected: {outcome.collected_count} unique profiles")
    print(f"After min-score filter ({args.min_score}+): {outcome.after_score_count}")
    print(f"After years filter: {outcome.after_years_count}")
    print(f"Exporting top {len(outcome.candidates)} candidates")
    print("=" * 60)

    if not outcome.candidates:
        print("No candidates matched the score threshold. Try lowering --min-score or --max-queries.")
        return 1

    print(f"\nExcel saved: {outcome.excel_path}")
    print(f"JSON backup: {outcome.json_path}")

    print("\nTop 10 candidates:")
    for index, candidate in enumerate(outcome.candidates[:10], start=1):
        headline = (candidate.headline or "")[:70]
        print(f"  {index:2}. [{candidate.fit_score:3}] {candidate.name} - {headline}")

    if args.enrich_top > 0:
        ok = sum(1 for e in outcome.enriched if e.status == "ok")
        print(f"\nEnriched {ok}/{len(outcome.enriched)} of the top {args.enrich_top} candidates via PersonScraper.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
