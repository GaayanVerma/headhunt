"""Pydantic models for the founder-grade Startup Readiness Evaluation stage.

This is a deliberate, isolated exception to the "no verdict" rule followed
everywhere else in this codebase (see models/github.py, models/ai_insights.py,
models/contributions.py). Every other layer documents that it never renders a
hiring verdict or single quality score - this module does, by design, because
it is the top-of-pipeline synthesis stage meant to be read directly by a
founder as a decision aid. It consumes those lower, non-judgmental layers as
its evidence base; it does not replace or alter them.
"""

from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, field_validator

ConfidenceLevel = Literal["LOW", "MEDIUM", "HIGH"]
Recommendation = Literal[
    "strong_match", "possible_match", "weak_match", "not_a_match"
]


class ReadinessDimensionAssessment(BaseModel):
    assessment: str
    confidence: ConfidenceLevel
    score: int
    """0-100, per the Scoring Framework bands: 0-20/21-50/51-80/81-100."""
    evidence_basis: List[str] = []

    @field_validator("score")
    @classmethod
    def _score_in_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("score must be between 0 and 100")
        return v


class ReadinessDimensions(BaseModel):
    ownership_and_proactivity: ReadinessDimensionAssessment
    execution_credibility: ReadinessDimensionAssessment
    drive_and_ambition: ReadinessDimensionAssessment
    adaptability: ReadinessDimensionAssessment


class OverallReadinessAssessment(BaseModel):
    summary: str
    confidence: ConfidenceLevel


class StartupReadinessEvaluation(BaseModel):
    """Founder-facing verdict, synthesized from Person + ResumeData +
    GitHubCandidateSummary. See module docstring for why this is allowed to
    render a judgment when nothing else in the pipeline does."""

    candidate_id: str
    overall_readiness_assessment: OverallReadinessAssessment
    overall_score: int
    """0-100, per the Scoring Framework bands: 0-20/21-50/51-80/81-100."""
    recommendation: Recommendation
    dimensions: ReadinessDimensions
    supporting_evidence: List[str] = []
    key_strengths: List[str] = []
    key_risks_or_unknowns: List[str] = []
    founder_takeaway: str
    input_limitations_acknowledged: List[str] = []
    candidate_narrative: Optional[str] = None
    """Short (2-3 sentence) candidate narrative summary, feeds
    headhunt_adapter.map_candidate_profile's `narrative` field."""

    # Bookkeeping, not part of the LLM-authored JSON schema.
    llm_model_used: Optional[str] = None
    generated_at: Optional[datetime] = None
    generation_error: Optional[str] = None  # non-null => degraded/skipped
    retry_count_used: int = 0

    # Raw text sidecars, persisted alongside the structured fields above but
    # not themselves part of the JSON schema.
    prose_report_markdown: Optional[str] = None
    framework_documentation_markdown: Optional[str] = None

    @field_validator("supporting_evidence")
    @classmethod
    def _max_three_supporting_evidence(cls, v: List[str]) -> List[str]:
        if len(v) > 3:
            raise ValueError("supporting_evidence must contain at most 3 items")
        return v

    @field_validator("overall_score")
    @classmethod
    def _overall_score_in_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("overall_score must be between 0 and 100")
        return v

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)
