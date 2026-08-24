"""Structured outputs for the sourcing crew's authority review stage."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CandidateVerdict(BaseModel):
    """Authority agent's judgment on a single candidate from either searcher."""

    name: str
    linkedin_url: str
    headline: Optional[str] = None
    location: Optional[str] = None
    sources: List[Literal["linkedin", "google"]] = Field(default_factory=list)
    fit_score: int = 0
    decision: Literal["shortlist", "maybe", "reject"] = "maybe"
    rationale: str = ""


class AuthorityReview(BaseModel):
    """Final reviewed shortlist produced by the high-authority agent."""

    shortlist: List[CandidateVerdict] = Field(default_factory=list)
    maybe: List[CandidateVerdict] = Field(default_factory=list)
    rejected_count: int = 0
    linkedin_count: int = 0
    google_count: int = 0
    overlap_count: int = 0
    summary: str = ""
