"""Thin async wrapper over the Serper.dev Google SERP API.

Used for X-ray candidate discovery (site:linkedin.com/in/ ... queries) since
scraping Google's HTML directly is fragile and gets blocked/CAPTCHA'd fast.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel

from ..core.auth import load_serper_key_from_env
from ..core.exceptions import LinkedInScraperException
from ..core.utils import retry_async

logger = logging.getLogger(__name__)

SERPER_SEARCH_URL = "https://google.serper.dev/search"

_RETRYABLE_EXCEPTIONS = (httpx.TransportError, httpx.TimeoutException)


class SerpSearchError(LinkedInScraperException):
    """Raised when a Serper.dev search fails or the API key is missing."""
    pass


class SerpResult(BaseModel):
    """A single raw organic search hit from Serper.dev - unparsed, not yet a candidate."""

    title: str
    link: str
    snippet: Optional[str] = None


class SerperClient:
    """Async client for Serper.dev's Google Search API."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0):
        self.api_key = api_key or load_serper_key_from_env()
        if not self.api_key:
            raise SerpSearchError(
                "SERPER_API_KEY not configured. Set it in .env or pass api_key= "
                "explicitly - see .env.example. X-ray discovery has no fallback "
                "search backend."
            )
        self._client = httpx.AsyncClient(
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SerperClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    @retry_async(max_attempts=3, backoff=2.0, exceptions=_RETRYABLE_EXCEPTIONS)
    async def search(self, query: str, num: int = 30, page: int = 1) -> List[SerpResult]:
        """Run a single Google search query via Serper.dev and return organic results."""
        response = await self._client.post(
            SERPER_SEARCH_URL,
            json={"q": query, "num": num, "page": page},
        )
        self._check_and_raise(response)

        try:
            payload: Dict[str, Any] = response.json()
        except ValueError as e:
            raise SerpSearchError(f"Serper.dev returned non-JSON response: {e}")

        organic = payload.get("organic", [])
        results: List[SerpResult] = []
        for item in organic:
            try:
                results.append(SerpResult(title=item.get("title", ""), link=item["link"], snippet=item.get("snippet")))
            except Exception as exc:
                logger.debug("Skipping malformed Serper result: %s", exc)
        return results

    def _check_and_raise(self, response: httpx.Response) -> None:
        if response.status_code == 401 or response.status_code == 403:
            raise SerpSearchError(
                f"Serper.dev auth error ({response.status_code}): {response.text[:300]}"
            )
        if response.status_code == 429:
            raise SerpSearchError(f"Serper.dev rate limit hit: {response.text[:300]}")
        if response.status_code >= 400:
            raise SerpSearchError(f"Serper.dev API {response.status_code}: {response.text[:300]}")
