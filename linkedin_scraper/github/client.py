"""Thin async wrapper over the GitHub GraphQL + REST APIs.

GraphQL is primary (profile + repo list + core repo fields in 1-3 calls).
REST is used only for what GraphQL can't give cheaply (file listings,
README, contributors) and as a fallback when GraphQL fails.
"""

import logging
from typing import Any, Dict, Optional

import httpx

from ..core.exceptions import NetworkError, RateLimitError
from ..core.utils import retry_async

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"
REST_BASE_URL = "https://api.github.com"

_RETRYABLE_EXCEPTIONS = (httpx.TransportError, httpx.TimeoutException, NetworkError)


class GitHubClient:
    """Async client handling auth headers, retries, and rate-limit bookkeeping."""

    def __init__(self, token: Optional[str] = None, timeout: float = 20.0):
        self.token = token
        self.authenticated = token is not None
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(headers=headers, timeout=timeout)
        self.rest_rate_limit_remaining: Optional[int] = None
        self.graphql_rate_limit_remaining: Optional[int] = None
        self.last_graphql_query_cost: Optional[int] = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    @retry_async(max_attempts=3, backoff=2.0, exceptions=_RETRYABLE_EXCEPTIONS)
    async def graphql(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        response = await self._client.post(
            GRAPHQL_URL, json={"query": query, "variables": variables}
        )
        self._check_and_raise(response)
        payload = response.json()
        if "errors" in payload and not payload.get("data"):
            raise NetworkError(f"GraphQL errors: {payload['errors']}")

        rate_limit = (payload.get("data") or {}).get("rateLimit")
        if rate_limit:
            self.graphql_rate_limit_remaining = rate_limit.get("remaining")
            self.last_graphql_query_cost = rate_limit.get("cost")

        return payload.get("data", {})

    @retry_async(max_attempts=3, backoff=2.0, exceptions=_RETRYABLE_EXCEPTIONS)
    async def rest_get(self, path: str, params: Optional[Dict[str, Any]] = None):
        """Returns (status_code, json_or_none, headers)."""
        url = path if path.startswith("http") else f"{REST_BASE_URL}{path}"
        response = await self._client.get(url, params=params)

        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            self.rest_rate_limit_remaining = int(remaining)

        if response.status_code == 404:
            return 404, None, response.headers
        if response.status_code == 202:
            # Stats not yet computed (e.g. contributors) - caller decides to retry once.
            return 202, None, response.headers

        self._check_and_raise(response)

        try:
            return response.status_code, response.json(), response.headers
        except ValueError:
            return response.status_code, None, response.headers

    def _check_and_raise(self, response: httpx.Response) -> None:
        if response.status_code == 403:
            retry_after = response.headers.get("retry-after")
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining == "0" or retry_after:
                raise RateLimitError(
                    f"GitHub rate limit hit (remaining={remaining}, retry_after={retry_after})",
                    suggested_wait_time=int(retry_after) if retry_after else 60,
                )
            raise NetworkError(f"GitHub API 403: {response.text[:300]}")
        if response.status_code >= 500:
            raise NetworkError(f"GitHub API {response.status_code}: {response.text[:300]}")
