"""Unit tests for LLM-backed and manual JD signal extraction - fake LLM client, no network."""

import json

import pytest

from linkedin_scraper.llm.base import LLMClient, LLMResponse, LLMError, LLMResponseParsingError
from linkedin_scraper.sourcing.jd_parser import extract_jd_signals, jd_signals_from_flags


def _valid_payload() -> dict:
    return {
        "titles": ["Senior Backend Engineer"],
        "must_have_skills": ["Python", "Django"],
        "nice_to_have_skills": ["Kubernetes"],
        "seniority": "senior",
        "min_years": 5,
        "max_years": None,
        "locations": ["Bangalore"],
        "company_stage": "startup",
        "excluded_terms": [],
    }


class _FakeLLMClient(LLMClient):
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, system_prompt, user_prompt, max_tokens=4096, temperature=0.0):
        self.calls += 1
        text = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        return LLMResponse(text=text, model="fake-model")


@pytest.mark.unit
class TestJdSignalsFromFlags:
    def test_maps_fields_directly(self):
        signals = jd_signals_from_flags(
            titles=["Founding Engineer"],
            must_have_skills=["TypeScript"],
            nice_to_have_skills=["AWS"],
            seniority="senior",
            min_years=2,
            max_years=5,
            locations=["Gurgaon"],
            company_stage="startup",
        )
        assert signals.titles == ["Founding Engineer"]
        assert signals.must_have_skills == ["TypeScript"]
        assert signals.extraction_source == "manual"

    def test_defaults_to_empty_lists(self):
        signals = jd_signals_from_flags()
        assert signals.titles == []
        assert signals.must_have_skills == []
        assert signals.extraction_source == "manual"


@pytest.mark.unit
class TestExtractJdSignals:
    async def test_valid_response_populates_signals(self):
        client = _FakeLLMClient([json.dumps(_valid_payload())])
        signals = await extract_jd_signals("Some JD text", llm_client=client)

        assert signals.titles == ["Senior Backend Engineer"]
        assert signals.must_have_skills == ["Python", "Django"]
        assert signals.extraction_source == "llm"
        assert signals.raw_jd_text == "Some JD text"
        assert client.calls == 1

    async def test_retries_once_on_malformed_json_then_succeeds(self):
        client = _FakeLLMClient(["not json at all", json.dumps(_valid_payload())])
        signals = await extract_jd_signals("Some JD text", llm_client=client)

        assert client.calls == 2
        assert signals.titles == ["Senior Backend Engineer"]

    async def test_raises_after_exhausting_retries_on_persistent_invalid_json(self):
        client = _FakeLLMClient(["not json", "still not json", "still not json"])
        with pytest.raises(LLMResponseParsingError):
            await extract_jd_signals("Some JD text", llm_client=client)

    async def test_raises_llm_error_without_key_or_client(self, monkeypatch):
        monkeypatch.setattr("linkedin_scraper.sourcing.jd_parser.load_anthropic_key_from_env", lambda: None)
        with pytest.raises(LLMError):
            await extract_jd_signals("Some JD text", llm_client=None)
