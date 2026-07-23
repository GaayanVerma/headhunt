"""
People search scraper for LinkedIn.

Searches for people on LinkedIn and extracts profile cards from results.
"""
import asyncio
import logging
import re
from typing import List, Optional, Set
from urllib.parse import urlencode

from playwright.async_api import Page

from ..callbacks import ProgressCallback, SilentCallback
from ..models.person_search import PersonSearchResult
from .base import BaseScraper

logger = logging.getLogger(__name__)

_PROFILE_URL_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[^/?#]+/?", re.I)


class PeopleSearchScraper(BaseScraper):
    """
    Scraper for LinkedIn people search results.

    Example:
        async with BrowserManager() as browser:
            scraper = PeopleSearchScraper(browser.page)
            results = await scraper.search(
                keywords="founding engineer typescript",
                location="Gurgaon",
                limit=50,
            )
    """

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def search(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 50,
        max_pages: int = 10,
        page_delay: float = 2.0,
    ) -> List[PersonSearchResult]:
        """
        Search for people on LinkedIn.

        Args:
            keywords: Search keywords (e.g. "founding engineer typescript")
            location: Location filter appended to keywords (e.g. "Gurgaon")
            limit: Maximum number of unique profiles to return for this query
            max_pages: Maximum pages to paginate through
            page_delay: Seconds to wait between page loads

        Returns:
            List of PersonSearchResult objects
        """
        query_label = self._query_label(keywords, location)
        logger.info("Starting people search: %s", query_label)

        search_url = self._build_search_url(keywords, location)
        await self.callback.on_start("PeopleSearch", search_url)

        results: List[PersonSearchResult] = []
        seen_urls: Set[str] = set()

        for page_num in range(1, max_pages + 1):
            if len(results) >= limit:
                break

            page_url = self._with_page(search_url, page_num)
            await self.navigate_and_wait(page_url)
            await self.wait_and_focus(1.5)

            if page_num == 1:
                await self.ensure_logged_in()

            await self.close_modals()

            try:
                await self.page.wait_for_selector('main a[href*="/in/"]', timeout=15000)
            except Exception:
                logger.warning("No people results found on page %s for %s", page_num, query_label)
                break

            await self.scroll_page_to_bottom(pause_time=0.8, max_scrolls=4)
            page_results = await self._extract_people_from_page()

            added = 0
            for result in page_results:
                if result.linkedin_url in seen_urls:
                    continue
                seen_urls.add(result.linkedin_url)
                result.search_query = query_label
                results.append(result)
                added += 1
                if len(results) >= limit:
                    break

            progress = min(95, int((len(results) / max(limit, 1)) * 90) + 5)
            await self.callback.on_progress(
                f"Page {page_num}: +{added} profiles ({len(results)}/{limit})",
                progress,
            )

            if added == 0:
                logger.info("No new profiles on page %s; stopping pagination", page_num)
                break

            if len(results) < limit and page_num < max_pages:
                await asyncio.sleep(page_delay)

        await self.callback.on_progress("Search complete", 100)
        await self.callback.on_complete("PeopleSearch", results)
        logger.info("People search complete for %s: found %d profiles", query_label, len(results))
        return results

    def _query_label(self, keywords: Optional[str], location: Optional[str]) -> str:
        parts = [part for part in (keywords, location) if part]
        return " | ".join(parts) if parts else "all"

    def _build_search_url(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
    ) -> str:
        """Build LinkedIn people search URL."""
        base_url = "https://www.linkedin.com/search/results/people/"
        search_terms = [part for part in (keywords, location) if part]
        params = {"origin": "GLOBAL_SEARCH_HEADER"}
        if search_terms:
            params["keywords"] = " ".join(search_terms)
        return f"{base_url}?{urlencode(params)}"

    def _with_page(self, search_url: str, page_num: int) -> str:
        if page_num <= 1:
            return search_url
        separator = "&" if "?" in search_url else "?"
        return f"{search_url}{separator}page={page_num}"

    async def _extract_people_from_page(self) -> List[PersonSearchResult]:
        """Extract people cards from the current search results page."""
        raw_results = await self.page.evaluate(
            """
            () => {
                const cleanUrl = (href) => {
                    if (!href) return null;
                    const url = href.split('?')[0].replace(/\\/$/, '');
                    if (!url.includes('/in/')) return null;
                    if (url.includes('/in/ACo')) return null;
                    return url;
                };

                const cards = [];
                const seen = new Set();
                const listItems = document.querySelectorAll('main li, main div[role="listitem"]');

                for (const item of listItems) {
                    const profileLinks = Array.from(item.querySelectorAll('a[href*="/in/"]'));
                    const profileLink = profileLinks.find((link) => {
                        const url = cleanUrl(link.href);
                        return url && !url.includes('/overlay/') && !url.includes('/detail/');
                    });
                    if (!profileLink) continue;

                    const linkedinUrl = cleanUrl(profileLink.href);
                    if (!linkedinUrl || seen.has(linkedinUrl)) continue;

                    const nameLink = profileLinks.find((link) => {
                        const text = (link.textContent || '').trim();
                        return text && text.length < 80 && !text.toLowerCase().includes('connect');
                    }) || profileLink;

                    let name = (nameLink.textContent || '').trim();
                    name = name.replace(/\\s*(Verified|Premium)\\s*$/i, '').trim();
                    name = name.replace(/\\s*•\\s*(1st|2nd|3rd\\+?).*$/i, '').trim();
                    if (!name || name.length < 2) continue;

                    const paragraphs = Array.from(item.querySelectorAll('p'))
                        .map((p) => (p.textContent || '').trim())
                        .filter(Boolean);

                    let headline = null;
                    let location = null;
                    let connectionDegree = null;
                    let mutualConnections = null;
                    let followers = null;

                    for (const text of paragraphs) {
                        if (text === name) continue;
                        if (/^•\\s*(1st|2nd|3rd\\+?)$/i.test(text) || /^•\\s*(1st|2nd|3rd\\+?)$/i.test(text.replace(name, '').trim())) {
                            const match = text.match(/(1st|2nd|3rd\\+?)/i);
                            if (match) connectionDegree = match[1];
                            continue;
                        }
                        if (/mutual connection/i.test(text)) {
                            mutualConnections = text;
                            continue;
                        }
                        if (/followers?/i.test(text) && /\\d/.test(text)) {
                            followers = text.replace(/^·\\s*/, '');
                            continue;
                        }
                        if (/try premium|actively hiring|search more efficiently/i.test(text)) continue;
                        if (!headline && text.length > 8 && !/^View my /i.test(text)) {
                            headline = text;
                            continue;
                        }
                        if (!location && headline && text !== headline && /,/.test(text)) {
                            location = text;
                        }
                    }

                    const itemText = item.textContent || '';
                    const isPremium = /Premium/i.test(itemText);
                    const isVerified = /Verified/i.test(itemText);

                    seen.add(linkedinUrl);
                    cards.push({
                        name,
                        linkedin_url: linkedinUrl,
                        headline,
                        location,
                        connection_degree: connectionDegree,
                        mutual_connections: mutualConnections,
                        followers,
                        is_premium: isPremium,
                        is_verified: isVerified,
                    });
                }

                return cards;
            }
            """
        )

        results: List[PersonSearchResult] = []
        for item in raw_results:
            url = item.get("linkedin_url", "")
            if not _PROFILE_URL_RE.match(url):
                continue
            try:
                results.append(PersonSearchResult(**item))
            except Exception as exc:
                logger.debug("Skipping invalid search result: %s", exc)

        return results
