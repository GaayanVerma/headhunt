#!/usr/bin/env python3
"""
Run the CrewAI dual-searcher sourcing crew with an authority reviewer.

Architecture:
  LinkedIn Searcher  ──┐
                       ├──► Authority Reviewer ──► shortlist JSON
  Google Searcher    ──┘

Prerequisites:
  1. pip install -e ".[crew]"
  2. ANTHROPIC_API_KEY in .env (CrewAI agents)
  3. SERPER_API_KEY in .env (Google X-ray tool)
  4. Optional linkedin_session.json for the LinkedIn searcher
     (otherwise pass --skip-linkedin)

Usage:
  python samples/run_sourcing_crew.py --jd-file jd.txt
  python samples/run_sourcing_crew.py --jd-file jd.txt --skip-linkedin
  python samples/run_sourcing_crew.py --jd-file jd.txt --process hierarchical
  python samples/run_sourcing_crew.py --no-llm --title "Founding Engineer" \\
      --must-have TypeScript --location Bangalore --skip-linkedin
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from linkedin_scraper.core.auth import load_anthropic_key_from_env, load_serper_key_from_env
from linkedin_scraper.llm.base import LLMError
from linkedin_scraper.models.jd_signals import JDSignals
from linkedin_scraper.sourcing import extract_jd_signals, jd_signals_from_flags


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CrewAI sourcing crew runner")
    parser.add_argument("--jd-file", type=Path, help="Path to free-text JD")
    parser.add_argument("--jd", type=str, help="JD text inline")
    parser.add_argument("--no-llm", action="store_true", help="Build JDSignals from flags")
    parser.add_argument("--title", action="append", default=[], help="Title (repeatable)")
    parser.add_argument("--must-have", action="append", default=[], dest="must_have")
    parser.add_argument("--nice-to-have", action="append", default=[], dest="nice_to_have")
    parser.add_argument("--location", action="append", default=[], dest="locations")
    parser.add_argument("--seniority", type=str, default=None)
    parser.add_argument("--min-years", type=int, default=None)
    parser.add_argument("--max-years", type=int, default=None)
    parser.add_argument(
        "--process",
        choices=("sequential", "hierarchical"),
        default="sequential",
        help="sequential: LinkedIn→Google→Authority. hierarchical: Authority manages.",
    )
    parser.add_argument("--skip-linkedin", action="store_true")
    parser.add_argument("--skip-skills-in-query", action="store_true")
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--shortlist-size", type=int, default=15)
    parser.add_argument("--model", default=None, help="CrewAI/litellm model id")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write review JSON here (default: candidates/crew_review_<ts>.json)",
    )
    return parser.parse_args()


async def _load_signals(args: argparse.Namespace) -> JDSignals:
    jd_text = args.jd
    if args.jd_file:
        jd_text = args.jd_file.read_text(encoding="utf-8")

    if args.no_llm or not jd_text:
        if not args.title and not args.must_have:
            raise SystemExit("Need --jd/--jd-file or --no-llm with --title/--must-have")
        return jd_signals_from_flags(
            titles=args.title,
            must_have_skills=args.must_have,
            nice_to_have_skills=args.nice_to_have,
            locations=args.locations,
            seniority=args.seniority,
            min_years=args.min_years,
            max_years=args.max_years,
            raw_jd_text=jd_text,
        )

    try:
        return await extract_jd_signals(jd_text)
    except LLMError as exc:
        raise SystemExit(
            f"JD signal extraction failed ({exc}). Re-run with --no-llm and flags."
        ) from exc


async def main() -> int:
    args = _parse_args()

    if not load_anthropic_key_from_env():
        print("ANTHROPIC_API_KEY missing — required for CrewAI agents.", file=sys.stderr)
        return 1
    if not load_serper_key_from_env():
        print("SERPER_API_KEY missing — required for the Google searcher tool.", file=sys.stderr)
        return 1

    try:
        from linkedin_scraper.crew import run_sourcing_crew
    except ImportError as exc:
        print(f"{exc}\nInstall with: pip install -e \".[crew]\"", file=sys.stderr)
        return 1

    signals = await _load_signals(args)
    print("JD signals:")
    print(json.dumps(signals.model_dump(), indent=2))

    result = run_sourcing_crew(
        signals,
        process=args.process,
        session_path=args.session,
        skip_linkedin=args.skip_linkedin,
        skip_skills_in_query=args.skip_skills_in_query,
        shortlist_size=args.shortlist_size,
        model=args.model,
        headless=args.headless,
    )

    out = args.out or Path("candidates") / f"crew_review_{datetime.now():%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    review = result["review"]
    print(f"\nAuthority summary: {review.get('summary', '')}")
    print(f"Shortlist ({len(review.get('shortlist', []))}):")
    for item in review.get("shortlist", []):
        print(
            f"  - {item.get('name')} | {item.get('linkedin_url')} | "
            f"sources={item.get('sources')} | {item.get('rationale', '')[:120]}"
        )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
