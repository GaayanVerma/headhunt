"""Generalized wrappers around the classic Playwright LinkedIn scraping scripts.

samples/scrape_person_contacts.py, scrape_company.py, scrape_company_posts.py,
and scrape_jobs.py currently hardcode a demo target with no CLI args - they
can't be reused as backend/chat tools until parameterized. This module is
that parameterization, plus the session-management flow extracted from
samples/create_session.py.

Every function here opens a REAL headed browser window (headless=False) -
LinkedIn blocks/degrades headless, and this app is explicitly local-only so
that a visible window on the operator's own machine is always an option.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from linkedin_scraper import BrowserManager, wait_for_manual_login
from linkedin_scraper.scrapers.company import CompanyScraper
from linkedin_scraper.scrapers.company_posts import CompanyPostsScraper
from linkedin_scraper.scrapers.job import JobScraper
from linkedin_scraper.scrapers.job_search import JobSearchScraper
from linkedin_scraper.scrapers.person import PersonScraper


def check_session_status(session_path: str = "linkedin_session.json") -> Dict[str, Any]:
    """File-existence + mtime check - can't verify a live login without a headed
    browser roundtrip, so this reports presence/age, not "still logged in"."""
    path = Path(session_path)
    if not path.exists():
        return {"exists": False, "modified_at": None}
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return {"exists": True, "modified_at": modified_at.isoformat()}


async def start_login_flow(session_path: str = "linkedin_session.json", timeout_ms: int = 300_000) -> Dict[str, Any]:
    """Open a real headed browser for manual LinkedIn login and save the session.

    Extracted from samples/create_session.py. Only works because this app is
    local-only - the browser window pops up on whichever machine runs it.
    """
    async with BrowserManager(headless=False) as browser:
        await browser.page.goto("https://www.linkedin.com/login")
        await wait_for_manual_login(browser.page, timeout=timeout_ms)
        await browser.save_session(session_path)
    return check_session_status(session_path)


async def scrape_profile(url: str, session_path: str = "linkedin_session.json") -> Dict[str, Any]:
    async with BrowserManager(headless=False) as browser:
        await browser.load_session(session_path)
        person = await PersonScraper(browser.page).scrape(url)
    return person.model_dump(mode="json")


async def scrape_company(url: str, session_path: str = "linkedin_session.json") -> Dict[str, Any]:
    async with BrowserManager(headless=False) as browser:
        await browser.load_session(session_path)
        company = await CompanyScraper(browser.page).scrape(url)
    return company.model_dump(mode="json")


async def scrape_company_posts(
    url: str, session_path: str = "linkedin_session.json", limit: int = 5
) -> List[Dict[str, Any]]:
    async with BrowserManager(headless=False) as browser:
        await browser.load_session(session_path)
        posts = await CompanyPostsScraper(browser.page).scrape(url, limit=limit)
    return [post.model_dump(mode="json") for post in posts]


async def search_jobs(
    keywords: str,
    location: str,
    session_path: str = "linkedin_session.json",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    async with BrowserManager(headless=False) as browser:
        await browser.load_session(session_path)
        job_urls = await JobSearchScraper(browser.page).search(keywords, location, limit=limit)
        job_scraper = JobScraper(browser.page)
        jobs = [await job_scraper.scrape(url) for url in job_urls]
    return [job.model_dump(mode="json") for job in jobs]
