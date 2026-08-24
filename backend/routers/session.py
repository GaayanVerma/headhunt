"""LinkedIn session status + manual-login endpoints.

start_login pops a REAL headed browser window on the machine running this
backend - only sensible because the whole app is local-only (see
backend/__init__.py).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..jobs import JOB_STORE
from ..schemas import JobStatusResponse, SessionStatusResponse
from ..services.scraping import check_session_status, start_login_flow

router = APIRouter(prefix="/api/session", tags=["session"])

DEFAULT_SESSION_PATH = "linkedin_session.json"


@router.get("/status")
async def session_status() -> SessionStatusResponse:
    return SessionStatusResponse(**check_session_status(DEFAULT_SESSION_PATH))


@router.post("/login")
async def start_login() -> JobStatusResponse:
    job = JOB_STORE.create(kind="login")

    async def _run() -> dict:
        return await start_login_flow(DEFAULT_SESSION_PATH)

    JOB_STORE.start(job.id, _run())
    return JobStatusResponse(job=job)
