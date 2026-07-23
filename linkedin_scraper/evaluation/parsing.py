"""Response parsing for the Startup Readiness Evaluation stage.

The LLM response here is NOT pure JSON like llm/json_parsing.py assumes -
it is prose (sections 1-3) + a fenced ```json block + a trailing fenced
Markdown Documentation block. This module owns its own extraction/validation/
retry loop rather than reusing complete_with_json_retry.
"""

import json
import logging
import re
from typing import Optional, Tuple

from ..llm.base import LLMClient, LLMResponseParsingError

logger = logging.getLogger(__name__)

_VALID_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}
_VALID_RECOMMENDATION = {"strong_match", "possible_match", "weak_match", "not_a_match"}
_REQUIRED_TOP_LEVEL_KEYS = (
    "candidate_id",
    "overall_readiness_assessment",
    "overall_score",
    "recommendation",
    "dimensions",
    "supporting_evidence",
    "key_strengths",
    "key_risks_or_unknowns",
    "founder_takeaway",
    "input_limitations_acknowledged",
)
_REQUIRED_DIMENSIONS = (
    "ownership_and_proactivity",
    "execution_credibility",
    "drive_and_ambition",
    "adaptability",
)


def _validate_score(value, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{field_name} must be an integer between 0 and 100, got {value!r}")

_FENCE_RE = re.compile(r"```(?P<lang>[a-zA-Z]*)\s*\n(?P<body>.*?)```", re.DOTALL)


def validate_readiness_json(parsed: dict) -> None:
    """Raises ValueError on missing/invalid fields."""
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in parsed:
            raise ValueError(f"missing required key: {key}")

    overall_confidence = (parsed.get("overall_readiness_assessment") or {}).get("confidence")
    if overall_confidence not in _VALID_CONFIDENCE:
        raise ValueError(f"invalid overall_readiness_assessment.confidence: {overall_confidence!r}")

    _validate_score(parsed.get("overall_score"), "overall_score")

    recommendation = parsed.get("recommendation")
    if recommendation not in _VALID_RECOMMENDATION:
        raise ValueError(f"invalid recommendation: {recommendation!r}")

    dimensions = parsed.get("dimensions") or {}
    for dim_key in _REQUIRED_DIMENSIONS:
        if dim_key not in dimensions:
            raise ValueError(f"dimensions missing required key: {dim_key}")
        dim_confidence = (dimensions[dim_key] or {}).get("confidence")
        if dim_confidence not in _VALID_CONFIDENCE:
            raise ValueError(f"invalid dimensions.{dim_key}.confidence: {dim_confidence!r}")
        _validate_score((dimensions[dim_key] or {}).get("score"), f"dimensions.{dim_key}.score")

    supporting_evidence = parsed.get("supporting_evidence")
    if not isinstance(supporting_evidence, list):
        raise ValueError("supporting_evidence must be a list")
    if len(supporting_evidence) > 3:
        raise ValueError(f"supporting_evidence must contain at most 3 items, got {len(supporting_evidence)}")

    for list_field in ("key_strengths", "key_risks_or_unknowns", "input_limitations_acknowledged"):
        value = parsed.get(list_field)
        if not isinstance(value, list):
            raise ValueError(f"{list_field} must be a list, got {type(value).__name__}")

    if not isinstance(parsed.get("candidate_id"), str) or not parsed["candidate_id"]:
        raise ValueError("candidate_id must be a non-empty string")

    if not isinstance(parsed.get("founder_takeaway"), str) or not parsed["founder_takeaway"]:
        raise ValueError("founder_takeaway must be a non-empty string")


def split_readiness_response(text: str) -> Tuple[str, dict, Optional[str]]:
    """Splits the raw LLM response text into (prose_markdown, parsed_json,
    framework_doc_markdown_or_None).

    Raises ValueError/json.JSONDecodeError if no ```json fence is found or its
    contents don't parse.
    """
    fences = list(_FENCE_RE.finditer(text))
    json_fence = next((m for m in fences if m.group("lang").lower() == "json"), None)
    if json_fence is None:
        raise ValueError("no fenced ```json block found in response")

    prose_markdown = text[: json_fence.start()].strip()
    parsed = json.loads(json_fence.group("body"))

    framework_doc_markdown = None
    trailing_fences = [m for m in fences if m.start() > json_fence.start()]
    if trailing_fences:
        framework_doc_markdown = trailing_fences[-1].group("body").strip()
    else:
        logger.warning(
            "No trailing Markdown Documentation fence found after the JSON block; "
            "framework_documentation_markdown will be None (non-fatal)."
        )

    return prose_markdown, parsed, framework_doc_markdown


async def complete_readiness_with_retry(
    llm: LLMClient,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 2,
    max_tokens: int = 8192,
) -> Tuple[dict, str, Optional[str], str, int]:
    """Calls llm.complete(), splits the 3-part response, validates the JSON
    schema, and retries with a corrective instruction on failure.

    Returns (parsed_json, prose_markdown, framework_doc_markdown, model_name,
    retry_count_used). Raises LLMResponseParsingError after exhausting retries.
    """
    prompt = user_prompt
    last_error: Exception = LLMResponseParsingError("no attempts made")
    model_name = ""

    for attempt in range(max_retries + 1):
        response = await llm.complete(system_prompt, prompt, max_tokens=max_tokens, temperature=0.0)
        model_name = response.model

        try:
            prose_markdown, parsed, framework_doc_markdown = split_readiness_response(response.text)
            validate_readiness_json(parsed)
            return parsed, prose_markdown, framework_doc_markdown, model_name, attempt
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning(f"Readiness evaluation response failed validation (attempt {attempt + 1}): {e}")
            prompt = (
                f"{user_prompt}\n\n"
                f"Your previous response did not include a valid fenced ```json block matching the "
                f"required schema, or failed validation: {e}. Re-emit the FULL response again - all "
                f"required sections in order (Startup Readiness Evaluation, Supporting Evidence, "
                f"Confidence and Limitations, Structured Output, Markdown Documentation) - with the "
                f"JSON block corrected."
            )

    raise LLMResponseParsingError(
        f"Readiness evaluation response invalid after {max_retries + 1} attempts: {last_error}"
    )
