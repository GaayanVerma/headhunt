"""CareerTimeline: a single, chronologically-sorted view over a candidate's
Person.experiences + Person.educations, tagged by deterministic rules only
(no LLM) - see evaluation/timeline_builder.py for the classification logic.

Replaces models/journey.py's LLM-driven promotion/transition/function/pivot
tagging, which only ever covered experiences (never education) and forced
every entry into one of 4 prose-defined kinds via an Anthropic API call.
`TimelineEntryKind` is instead sourced directly from LinkedIn's own
employment-type label (already scraped, see Experience.employment_type) or
set to "education" - never guessed.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

TimelineEntryKind = Literal[
    "education",
    "internship",
    "full_time",
    "part_time",
    "contract",
    "freelance",
    "self_employed",
    "apprenticeship",
    "seasonal",
    "unknown",
]

TimelineTransitionKind = Literal["first_role", "promotion", "transition", "function_change"]


class TimelineEntry(BaseModel):
    """One chronological entry (either a job or a degree)."""

    kind: TimelineEntryKind
    transition: Optional[TimelineTransitionKind] = None
    """Only set on work entries (None for education)."""
    title: Optional[str] = None
    """position_title for work entries, degree for education entries."""
    institution: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None
    domain_changed: bool = False
    """True when institution differs from the previous work entry's. Always
    False for education and for the first work entry."""
    source: Literal["linkedin"] = "linkedin"


class CareerTimeline(BaseModel):
    """Chronological (oldest -> newest) merge of experiences + educations."""

    entries: List[TimelineEntry] = Field(default_factory=list)
    total_years_experience: Optional[float] = None
