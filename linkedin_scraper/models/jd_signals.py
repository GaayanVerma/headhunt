"""Pydantic model for structured signals extracted from a job description."""

from typing import List, Optional
from pydantic import BaseModel, Field


class JDSignals(BaseModel):
    """Structured search/scoring signals derived from a free-text JD.

    Produced either by LLM extraction (sourcing/jd_parser.py::extract_jd_signals)
    or by manual CLI flags (sourcing/jd_parser.py::jd_signals_from_flags) -
    extraction_source records which, so exported runs stay self-documenting.
    """

    titles: List[str] = Field(default_factory=list)
    must_have_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    min_years: Optional[int] = None
    max_years: Optional[int] = None
    locations: List[str] = Field(default_factory=list)
    company_stage: Optional[str] = None
    excluded_terms: List[str] = Field(default_factory=list)
    raw_jd_text: Optional[str] = None
    extraction_source: str = "manual"
