"""Unit tests for the readiness evaluation response parser - no network/LLM calls."""

import json

import pytest

from linkedin_scraper.evaluation.parsing import split_readiness_response, validate_readiness_json


def _valid_json_payload() -> dict:
    dim = {"assessment": "x", "confidence": "MEDIUM", "score": 60, "evidence_basis": ["a"]}
    return {
        "candidate_id": "octocat",
        "overall_readiness_assessment": {"summary": "s", "confidence": "MEDIUM"},
        "overall_score": 60,
        "recommendation": "possible_match",
        "dimensions": {
            "ownership_and_proactivity": dim,
            "execution_credibility": dim,
            "drive_and_ambition": dim,
            "adaptability": dim,
        },
        "supporting_evidence": ["e1", "e2"],
        "key_strengths": ["strong"],
        "key_risks_or_unknowns": ["risk"],
        "founder_takeaway": "takeaway",
        "input_limitations_acknowledged": ["limited data"],
    }


def _build_response(payload: dict, include_doc: bool = True) -> str:
    text = (
        "## Startup Readiness Evaluation\nprose\n\n"
        "## Supporting Evidence\n- e1\n\n"
        "## Confidence and Limitations\n- limited\n\n"
        "## Structured Output\n```json\n" + json.dumps(payload) + "\n```\n"
    )
    if include_doc:
        text += "\n## Markdown Documentation\n```markdown\n# Framework Doc\nbody\n```\n"
    return text


@pytest.mark.unit
def test_split_readiness_response_extracts_all_three_parts():
    payload = _valid_json_payload()
    text = _build_response(payload)
    prose, parsed, doc = split_readiness_response(text)

    assert "Startup Readiness Evaluation" in prose
    assert parsed == payload
    assert doc is not None and "Framework Doc" in doc


@pytest.mark.unit
def test_split_readiness_response_handles_missing_doc_block():
    payload = _valid_json_payload()
    text = _build_response(payload, include_doc=False)
    prose, parsed, doc = split_readiness_response(text)

    assert parsed == payload
    assert doc is None


@pytest.mark.unit
def test_split_readiness_response_raises_without_json_fence():
    with pytest.raises(ValueError):
        split_readiness_response("no fenced json here")


@pytest.mark.unit
def test_validate_readiness_json_accepts_valid_payload():
    validate_readiness_json(_valid_json_payload())  # should not raise


@pytest.mark.unit
def test_validate_readiness_json_rejects_missing_key():
    payload = _valid_json_payload()
    del payload["founder_takeaway"]
    with pytest.raises(ValueError):
        validate_readiness_json(payload)


@pytest.mark.unit
def test_validate_readiness_json_rejects_too_much_supporting_evidence():
    payload = _valid_json_payload()
    payload["supporting_evidence"] = ["e1", "e2", "e3", "e4"]
    with pytest.raises(ValueError):
        validate_readiness_json(payload)


@pytest.mark.unit
def test_validate_readiness_json_rejects_invalid_confidence_band():
    payload = _valid_json_payload()
    payload["dimensions"]["adaptability"]["confidence"] = "SUPER_HIGH"
    with pytest.raises(ValueError):
        validate_readiness_json(payload)
