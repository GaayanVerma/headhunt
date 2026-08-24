"""Turn a free-text job description into JDSignals - either via LLM extraction
or a deterministic manual-flags fallback when no ANTHROPIC_API_KEY is configured.

JD-signal extraction is the entire input to the discovery pipeline (not an
optional enrichment stage), so failure here must be explicit and catchable -
callers switch to jd_signals_from_flags rather than silently proceeding with
empty signals.
"""

from typing import List, Optional

from ..core.auth import load_anthropic_key_from_env
from ..llm.base import LLMClient, LLMError
from ..llm.anthropic_client import AnthropicLLMClient
from ..llm.json_parsing import complete_with_json_retry, validate_jd_signals_json
from ..llm.prompts import (
    JD_SIGNAL_EXTRACTION_SYSTEM_PROMPT,
    render_jd_signal_extraction_user_prompt,
)
from ..models.jd_signals import JDSignals


async def extract_jd_signals(jd_text: str, llm_client: Optional[LLMClient] = None) -> JDSignals:
    """
    LLM-backed JD -> JDSignals extraction.

    Raises LLMError if no ANTHROPIC_API_KEY is configured and no llm_client
    was passed, or LLMResponseParsingError if the LLM's output can't be
    parsed into the expected schema after retries. Callers must catch these
    and fall back to jd_signals_from_flags - never silently return empty signals.
    """
    if llm_client is None:
        api_key = load_anthropic_key_from_env()
        if not api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY not configured - cannot auto-extract JD signals. "
                "Use jd_signals_from_flags(...) or pass --title/--must-have/etc. flags instead."
            )
        llm_client = AnthropicLLMClient(api_key=api_key)

    parsed, _retry_count, _model_name = await complete_with_json_retry(
        llm_client,
        JD_SIGNAL_EXTRACTION_SYSTEM_PROMPT,
        render_jd_signal_extraction_user_prompt(jd_text),
        schema_validator=validate_jd_signals_json,
    )

    return JDSignals(
        titles=parsed["titles"],
        must_have_skills=parsed["must_have_skills"],
        nice_to_have_skills=parsed["nice_to_have_skills"],
        seniority=parsed.get("seniority"),
        min_years=parsed.get("min_years"),
        max_years=parsed.get("max_years"),
        locations=parsed["locations"],
        company_stage=parsed.get("company_stage"),
        excluded_terms=parsed["excluded_terms"],
        raw_jd_text=jd_text,
        extraction_source="llm",
    )


def jd_signals_from_flags(
    titles: Optional[List[str]] = None,
    must_have_skills: Optional[List[str]] = None,
    nice_to_have_skills: Optional[List[str]] = None,
    seniority: Optional[str] = None,
    min_years: Optional[int] = None,
    max_years: Optional[int] = None,
    locations: Optional[List[str]] = None,
    company_stage: Optional[str] = None,
    excluded_terms: Optional[List[str]] = None,
    raw_jd_text: Optional[str] = None,
) -> JDSignals:
    """Deterministic, zero-network JDSignals constructor for the manual CLI-flag fallback."""
    return JDSignals(
        titles=titles or [],
        must_have_skills=must_have_skills or [],
        nice_to_have_skills=nice_to_have_skills or [],
        seniority=seniority,
        min_years=min_years,
        max_years=max_years,
        locations=locations or [],
        company_stage=company_stage,
        excluded_terms=excluded_terms or [],
        raw_jd_text=raw_jd_text,
        extraction_source="manual",
    )
