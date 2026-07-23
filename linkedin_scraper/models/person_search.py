"""Pydantic models for LinkedIn people search results."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class PersonSearchResult(BaseModel):
    """A single person card from LinkedIn people search results."""

    name: str
    linkedin_url: str
    headline: Optional[str] = None
    location: Optional[str] = None
    connection_degree: Optional[str] = None
    mutual_connections: Optional[str] = None
    followers: Optional[str] = None
    is_premium: bool = False
    is_verified: bool = False
    search_query: Optional[str] = None
    fit_score: int = 0
    fit_indicators: List[str] = Field(default_factory=list)

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, value: str) -> str:
        if "linkedin.com/in/" not in value:
            raise ValueError("Must be a valid LinkedIn profile URL (contains /in/)")
        return value.rstrip("/")

    @property
    def fit_indicators_text(self) -> str:
        return "; ".join(self.fit_indicators)
