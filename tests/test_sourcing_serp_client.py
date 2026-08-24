"""Unit tests for the Serper.dev SERP client and its env-var loader."""

import httpx
import pytest

from linkedin_scraper.core.auth import load_serper_key_from_env
from linkedin_scraper.sourcing.serp_client import SerperClient, SerpSearchError


def _fake_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", "https://google.serper.dev/search"))


@pytest.mark.unit
class TestLoadSerperKeyFromEnv:
    def test_returns_key_when_set(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "test-key-123")
        assert load_serper_key_from_env() == "test-key-123"

    def test_returns_none_when_unset(self, monkeypatch):
        # Also stub out load_dotenv, since a real .env on disk (with a real
        # key, for live use) would otherwise repopulate the env var we just
        # deleted the moment load_serper_key_from_env() calls it.
        monkeypatch.setattr("linkedin_scraper.core.auth.load_dotenv", lambda: None)
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        assert load_serper_key_from_env() is None


@pytest.mark.unit
class TestSerperClientConstruction:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.setattr("linkedin_scraper.sourcing.serp_client.load_serper_key_from_env", lambda: None)
        with pytest.raises(SerpSearchError):
            SerperClient(api_key=None)

    def test_accepts_explicit_api_key(self):
        client = SerperClient(api_key="explicit-key")
        assert client.api_key == "explicit-key"


@pytest.mark.unit
class TestSerperClientSearch:
    async def test_parses_organic_results(self, monkeypatch):
        client = SerperClient(api_key="test-key")
        payload = {
            "organic": [
                {"title": "Jane Doe - Engineer | LinkedIn", "link": "https://www.linkedin.com/in/jane-doe/", "snippet": "Bangalore"},
                {"title": "No link field"},
            ]
        }

        async def fake_post(*args, **kwargs):
            return _fake_response(200, payload)

        monkeypatch.setattr(client._client, "post", fake_post)
        results = await client.search("site:linkedin.com/in/ engineer")

        assert len(results) == 1
        assert results[0].link == "https://www.linkedin.com/in/jane-doe/"
        await client.aclose()

    async def test_raises_on_error_status(self, monkeypatch):
        client = SerperClient(api_key="test-key")

        async def fake_post(*args, **kwargs):
            return _fake_response(401, {"message": "invalid key"})

        monkeypatch.setattr(client._client, "post", fake_post)
        with pytest.raises(SerpSearchError):
            await client.search("query")
        await client.aclose()

    async def test_retries_on_timeout_then_succeeds(self, monkeypatch):
        client = SerperClient(api_key="test-key")
        payload = {"organic": [{"title": "Jane Doe - Engineer | LinkedIn", "link": "https://www.linkedin.com/in/jane-doe/"}]}
        calls = {"count": 0}

        async def flaky_post(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.TimeoutException("timed out")
            return _fake_response(200, payload)

        monkeypatch.setattr(client._client, "post", flaky_post)
        results = await client.search("query")

        assert calls["count"] == 2
        assert len(results) == 1
        await client.aclose()
