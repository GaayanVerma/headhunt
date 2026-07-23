"""
Scrape a LinkedIn profile and/or parse a resume PDF.

Usage:
    # Parse resume only
    python samples/scrape_with_resume.py --resume path/to/resume.pdf

    # Scrape LinkedIn profile only
    python samples/scrape_with_resume.py --linkedin-url https://www.linkedin.com/in/someone/

    # Both together
    python samples/scrape_with_resume.py \
        --linkedin-url https://www.linkedin.com/in/someone/ \
        --resume path/to/resume.pdf \
        --session linkedin_session.json
"""

import argparse
import asyncio
import json
import sys

sys.path.insert(0, ".")

from linkedin_scraper import BrowserManager, PersonScraper, ResumeParser


async def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn scraper + resume parser")
    parser.add_argument("--linkedin-url", help="LinkedIn profile URL to scrape")
    parser.add_argument("--resume", help="Path to PDF resume")
    parser.add_argument(
        "--session",
        default="linkedin_session.json",
        help="Path to LinkedIn session file (default: linkedin_session.json)",
    )
    args = parser.parse_args()

    if not args.linkedin_url and not args.resume:
        parser.error("Provide at least --linkedin-url or --resume")

    result = {}

    # Resume parsing (sync, no browser needed)
    if args.resume:
        print(f"Parsing resume: {args.resume}")
        resume_data = ResumeParser().parse(args.resume)
        result["resume"] = resume_data.to_dict()
        result["resume"].pop("raw_text", None)  # omit wall of text from output

    # LinkedIn scraping
    if args.linkedin_url:
        print(f"Scraping LinkedIn: {args.linkedin_url}")
        async with BrowserManager(headless=False) as browser:
            await browser.load_session(args.session)
            scraper = PersonScraper(browser.page)
            person = await scraper.scrape(args.linkedin_url)
        result["linkedin"] = person.to_dict()

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
