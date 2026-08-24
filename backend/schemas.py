"""Request/response models for the backend API.

XraySearchRequest is XraySearchParams itself (not redefined) - the CLI, this
API, and the chat tool's input_schema all share one field list, so "every
flag has a UI control" can't silently drift out of sync.
"""

from __future__ import annotations

from linkedin_scraper.sourcing import XraySearchParams
from pydantic import BaseModel

from .jobs import Job

XraySearchRequest = XraySearchParams


class JobStatusResponse(BaseModel):
    job: Job


class SessionStatusResponse(BaseModel):
    exists: bool
    modified_at: str | None = None
