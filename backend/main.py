"""FastAPI app entry point.

Run with: uvicorn backend.main:app --reload --port 8000
Local-only by design (see backend/__init__.py) - CORS is scoped to the Vite
dev server origin, not opened up for arbitrary remote clients.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import chat, session, xray

app = FastAPI(title="Candidate Sourcing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(xray.router)
app.include_router(session.router)
app.include_router(chat.router)

# Serves exported xlsx/json files for direct linking if needed; the primary
# download path is GET /api/xray/download/{job_id}/{kind}, which streams a
# specific job's files without exposing the whole directory.
app.mount("/files", StaticFiles(directory="candidates", check_dir=False), name="files")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
