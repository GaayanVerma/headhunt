"""Pydantic model for parsed resume data."""

from typing import List, Optional
from pydantic import BaseModel


class ResumeProject(BaseModel):
    """A single project entry parsed from a resume's Projects section."""

    name: Optional[str] = None
    description: Optional[str] = None
    technologies: List[str] = []


class ResumeData(BaseModel):
    """Structured data extracted from a PDF resume."""

    raw_text: str = ""
    links: List[str] = []
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    other_urls: List[str] = []
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: List[str] = []
    projects: List[ResumeProject] = []

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)
