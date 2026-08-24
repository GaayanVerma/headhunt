"""X-ray JD search endpoints - the classic form's backend."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from linkedin_scraper.sourcing import run_xray_search

from ..jobs import JOB_STORE, JobProgressCallback, JobStatus
from ..schemas import JobStatusResponse, XraySearchRequest

router = APIRouter(prefix="/api", tags=["xray"])


@router.post("/xray/search")
async def start_xray_search(req: XraySearchRequest) -> JobStatusResponse:
    if not req.jd_file and not req.jd_text and not (req.title or req.must_have):
        raise HTTPException(status_code=422, detail="Provide jd_file, jd_text, or manual title/must_have values.")

    job = JOB_STORE.create(kind="xray_search")
    callback = JobProgressCallback(JOB_STORE, job.id)

    async def _run() -> dict:
        outcome = await run_xray_search(req, callback=callback)
        return outcome.model_dump(mode="json")

    JOB_STORE.start(job.id, _run())
    return JobStatusResponse(job=job)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> JobStatusResponse:
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(job=job)


@router.get("/xray/download/{job_id}/{kind}")
async def download(job_id: str, kind: str) -> FileResponse:
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.succeeded or job.result is None:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, no result yet")
    if kind not in ("excel", "json"):
        raise HTTPException(status_code=400, detail="kind must be 'excel' or 'json'")

    path_key = "excel_path" if kind == "excel" else "json_path"
    path = Path(job.result[path_key])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path} no longer exists on disk")
    return FileResponse(path, filename=path.name)
