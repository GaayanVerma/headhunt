"""Unit tests for JD-signals JSON schema validation."""

import pytest

from linkedin_scraper.llm.json_parsing import validate_jd_signals_json


def _valid_payload() -> dict:
    return {
        "titles": ["Senior Backend Engineer"],
        "must_have_skills": ["Python"],
        "nice_to_have_skills": [],
        "seniority": "senior",
        "min_years": 3,
        "max_years": None,
        "locations": ["Bangalore"],
        "company_stage": "startup",
        "excluded_terms": [],
    }


@pytest.mark.unit
class TestValidateJdSignalsJson:
    def test_valid_minimal_doc_passes(self):
        validate_jd_signals_json(_valid_payload())

    def test_missing_required_key_raises(self):
        payload = _valid_payload()
        del payload["titles"]
        with pytest.raises(ValueError):
            validate_jd_signals_json(payload)

    def test_wrong_type_for_list_field_raises(self):
        payload = _valid_payload()
        payload["must_have_skills"] = "python"
        with pytest.raises(ValueError):
            validate_jd_signals_json(payload)

    def test_invalid_seniority_raises(self):
        payload = _valid_payload()
        payload["seniority"] = "expert"
        with pytest.raises(ValueError):
            validate_jd_signals_json(payload)

    def test_invalid_company_stage_raises(self):
        payload = _valid_payload()
        payload["company_stage"] = "unicorn"
        with pytest.raises(ValueError):
            validate_jd_signals_json(payload)

    def test_non_int_years_raises(self):
        payload = _valid_payload()
        payload["min_years"] = "three"
        with pytest.raises(ValueError):
            validate_jd_signals_json(payload)

    def test_null_optional_fields_are_allowed(self):
        payload = _valid_payload()
        payload["seniority"] = None
        payload["company_stage"] = None
        payload["min_years"] = None
        payload["max_years"] = None
        validate_jd_signals_json(payload)
