"""In-memory async job store.

Every long-running operation in this app (X-ray search, classic scraping,
chat tool calls) runs as a background asyncio task tracked here, polled via
GET /api/jobs/{id}. One in-memory store is intentional, not a shortcut to
fix later: this app is a single local operator's tool, not a scaled
service, so there's no need for Redis/Celery/a real queue.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Coroutine, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from linkedin_scraper.callbacks import ProgressCallback

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Job(BaseModel):
    id: str
    kind: str
    status: JobStatus = JobStatus.pending
    progress_percent: int = 0
    progress_message: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobStore:
    """In-memory job registry; one instance (JOB_STORE below) for the whole app."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def create(self, kind: str) -> Job:
        job = Job(id=str(uuid4()), kind=kind, created_at=_now(), updated_at=_now())
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **fields: Any) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _now()

    def start(self, job_id: str, coro: Coroutine[Any, Any, Dict[str, Any]]) -> None:
        """Run coro in the background, updating the job's status as it progresses.

        coro must resolve to a JSON-serializable dict (callers typically pass
        `some_outcome.model_dump(mode="json")` at the end of their coroutine).
        """

        async def _runner() -> None:
            self.update(job_id, status=JobStatus.running)
            try:
                result = await coro
                self.update(job_id, status=JobStatus.succeeded, result=result, progress_percent=100)
            except Exception as exc:  # noqa: BLE001 - job failures must not crash the event loop
                logger.exception("Job %s (%s) failed", job_id, self._jobs[job_id].kind if job_id in self._jobs else "?")
                self.update(job_id, status=JobStatus.failed, error=f"{exc}\n{traceback.format_exc(limit=3)}")

        self._tasks[job_id] = asyncio.create_task(_runner())


class JobProgressCallback(ProgressCallback):
    """Bridges the existing ProgressCallback interface into JobStore updates."""

    def __init__(self, store: JobStore, job_id: str):
        self.store = store
        self.job_id = job_id

    async def on_start(self, scraper_type: str, url: str) -> None:
        self.store.update(self.job_id, progress_message=f"Starting {scraper_type}: {url}", progress_percent=0)

    async def on_progress(self, message: str, percent: int) -> None:
        self.store.update(self.job_id, progress_message=message, progress_percent=percent)

    async def on_complete(self, scraper_type: str, result: Any) -> None:
        self.store.update(self.job_id, progress_message=f"Completed {scraper_type}")

    async def on_error(self, error: Exception) -> None:
        self.store.update(self.job_id, progress_message=f"Error: {error}")


JOB_STORE = JobStore()
