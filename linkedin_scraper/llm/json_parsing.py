"""Strict JSON extraction and schema validation for LLM repo-insight responses,
with a bounded retry loop when the model returns malformed or schema-invalid JSON."""

import json
import logging
import re
from typing import Callable, Tuple

from .base import LLMClient, LLMResponseParsingError

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_VALID_BANDS = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}


def _strip_markdown_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def validate_repo_insight_json(parsed: dict) -> None:
    """Raises ValueError on missing/invalid fields. A non-UNKNOWN band with
    zero evidence entries is rejected to enforce the evidence-citation rule."""
    required = ("repo_summary", "code_quality", "confidence", "evidence_files")
    for key in required:
        if key not in parsed:
            raise ValueError(f"missing required key: {key}")

    top_confidence = parsed.get("confidence")
    if top_confidence not in _VALID_BANDS:
        raise ValueError(f"invalid confidence band: {top_confidence!r}")

    if top_confidence != "UNKNOWN" and not parsed.get("evidence_files"):
        raise ValueError("non-UNKNOWN confidence with zero evidence_files")

    workflow_steps = parsed.get("workflow_steps")
    if workflow_steps is not None:
        if not isinstance(workflow_steps, list):
            raise ValueError("workflow_steps must be a list")
        for step in workflow_steps:
            if not isinstance(step, dict):
                raise ValueError("workflow_steps entries must be objects")
            for field in ("step_order", "actor", "action"):
                if field not in step:
                    raise ValueError(f"workflow_steps entry missing required key: {field}")
            if not isinstance(step["step_order"], int):
                raise ValueError("workflow_steps.step_order must be an int")

    code_quality = parsed.get("code_quality") or {}
    banded_fields = (
        "readability", "modularity", "project_structure_clarity", "dependency_hygiene",
        "testing_presence", "documentation_quality", "ci_cd_presence", "deployability",
        "confidence",
    )
    for field in banded_fields:
        value = code_quality.get(field)
        if value not in _VALID_BANDS:
            raise ValueError(f"invalid code_quality.{field} band: {value!r}")
        if field != "confidence" and value != "UNKNOWN" and not code_quality.get("evidence"):
            raise ValueError(f"code_quality.{field}={value!r} with zero evidence entries")


_VALID_SENIORITY = {"junior", "mid", "senior", "staff+"}
_VALID_COMPANY_STAGE = {"startup", "growth", "enterprise"}

_JD_SIGNALS_LIST_FIELDS = (
    "titles", "must_have_skills", "nice_to_have_skills", "locations", "excluded_terms",
)


def validate_jd_signals_json(parsed: dict) -> None:
    """Raises ValueError on missing/invalid fields. Looser than
    validate_repo_insight_json - structured extraction, not a claims-with-evidence
    task, so there's no evidence-citation requirement."""
    required = (
        "titles", "must_have_skills", "nice_to_have_skills", "seniority",
        "min_years", "max_years", "locations", "company_stage", "excluded_terms",
    )
    for key in required:
        if key not in parsed:
            raise ValueError(f"missing required key: {key}")

    for field in _JD_SIGNALS_LIST_FIELDS:
        value = parsed[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be a list of strings")

    seniority = parsed.get("seniority")
    if seniority is not None and seniority not in _VALID_SENIORITY:
        raise ValueError(f"invalid seniority: {seniority!r}")

    company_stage = parsed.get("company_stage")
    if company_stage is not None and company_stage not in _VALID_COMPANY_STAGE:
        raise ValueError(f"invalid company_stage: {company_stage!r}")

    for field in ("min_years", "max_years"):
        value = parsed.get(field)
        if value is not None and not isinstance(value, int):
            raise ValueError(f"{field} must be an int or null")


async def complete_with_json_retry(
    llm: LLMClient,
    system_prompt: str,
    user_prompt: str,
    schema_validator: Callable[[dict], None] = validate_repo_insight_json,
    max_retries: int = 2,
    max_tokens: int = 4096,
) -> Tuple[dict, int, str]:
    """Calls llm.complete(), strips markdown fences if present, json.loads()s,
    and runs schema_validator(parsed). On JSONDecodeError or ValueError, appends
    a corrective follow-up instruction and retries up to max_retries times.

    Returns (parsed_dict, retry_count_used, model_name). Raises
    LLMResponseParsingError if still invalid after all retries.
    """
    prompt = user_prompt
    last_error: Exception = LLMResponseParsingError("no attempts made")
    model_name = ""

    for attempt in range(max_retries + 1):
        response = await llm.complete(system_prompt, prompt, max_tokens=max_tokens, temperature=0.0)
        model_name = response.model
        text = _strip_markdown_fences(response.text)

        try:
            parsed = json.loads(text)
            schema_validator(parsed)
            return parsed, attempt, model_name
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning(f"LLM response failed JSON/schema validation (attempt {attempt + 1}): {e}")
            prompt = (
                f"{user_prompt}\n\n"
                f"Your previous response was not valid JSON matching the schema: {e}. "
                f"Return ONLY corrected JSON."
            )

    raise LLMResponseParsingError(
        f"LLM response invalid after {max_retries + 1} attempts: {last_error}"
    )
