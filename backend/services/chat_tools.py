"""Tool definitions and dispatch for the chat orchestrator.

Every tool here is either long-running (creates a Job via the same JobStore
used by the classic-search form and returns {"job_id": ...} immediately) or
cheap enough to run synchronously in the tool-turn. dispatch_tool is the one
place that maps a tool_use block's name to the actual backend call.
"""

from __future__ import annotations

from typing import Any, Dict, List

from linkedin_scraper.export import export_candidates_to_excel
from linkedin_scraper.models.person_search import PersonSearchResult

from ..jobs import JobStore
from . import scraping
from .crew_search import run_candidate_search_crew

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "run_candidate_search_crew",
        "description": (
            "Search for candidates matching a role, using a LinkedIn Searcher agent and a "
            "Google X-ray Searcher agent whose results a third Authority Reviewer agent "
            "merges, dedupes, quality-bars, and shortlists. This is the primary candidate "
            "discovery tool - use it whenever the user asks to find/source candidates. "
            "Prefer giving jd_text (paste of the JD) when the user provided one; otherwise "
            "give titles/must_have_skills directly. This is expensive (multiple LLM calls, "
            "possibly a real browser search) - don't call it until you have enough signal "
            "to make a meaningful search (at minimum a role/title and a couple of skills or "
            "a JD). Ask a clarifying question first if the ask is too thin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "jd_text": {"type": "string", "description": "Free-text job description, if the user gave one."},
                "titles": {"type": "array", "items": {"type": "string"}},
                "must_have_skills": {"type": "array", "items": {"type": "string"}},
                "nice_to_have_skills": {"type": "array", "items": {"type": "string"}},
                "seniority": {"type": "string", "enum": ["junior", "mid", "senior", "staff+"]},
                "locations": {"type": "array", "items": {"type": "string"}},
                "min_years": {"type": "integer"},
                "max_years": {"type": "integer"},
                "process": {
                    "type": "string",
                    "enum": ["sequential", "hierarchical"],
                    "description": "sequential (default): LinkedIn -> Google -> Authority review. "
                    "hierarchical: Authority manages and can delegate follow-up searches.",
                },
            },
        },
    },
    {
        "name": "scrape_linkedin_profile",
        "description": "Deep-scrape a single LinkedIn profile URL for full details. Requires a saved LinkedIn session.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "scrape_company",
        "description": "Scrape a LinkedIn company page (overview, industry, size, HQ).",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "scrape_company_posts",
        "description": "Scrape a company's recent LinkedIn posts (reactions/comments/reposts).",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "limit": {"type": "integer", "default": 5}},
            "required": ["url"],
        },
    },
    {
        "name": "search_jobs",
        "description": "Search LinkedIn job postings by keywords and location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string"},
                "location": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["keywords", "location"],
        },
    },
    {
        "name": "check_session_status",
        "description": "Check whether a LinkedIn session file exists and how old it is.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "start_login_flow",
        "description": (
            "Open a real browser window on the operator's machine for manual LinkedIn login, "
            "and save the resulting session. Only call this if the user explicitly asks to log "
            "in / re-authenticate - it opens a visible window and waits up to 5 minutes."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "export_candidate_subset",
        "description": (
            "Export a filtered subset of candidates already surfaced in this conversation "
            "(by linkedin_url) to a downloadable Excel/JSON file, without re-running a search. "
            "Use this when the user asks to narrow down or save a specific slice of results "
            "already shown, e.g. 'just the ones in Bangalore' or 'drop anyone without AWS'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "linkedin_urls": {"type": "array", "items": {"type": "string"}},
                "label": {"type": "string", "description": "Short label used in the output filename."},
            },
            "required": ["linkedin_urls", "label"],
        },
    },
]


async def dispatch_tool(
    name: str,
    tool_input: Dict[str, Any],
    job_store: JobStore,
    last_results: Dict[str, PersonSearchResult],
) -> Dict[str, Any]:
    """Route a tool_use call. Long-running tools return {"job_id": ...} for the
    frontend/caller to poll; cheap tools return their result directly."""

    if name == "run_candidate_search_crew":
        job = job_store.create(kind="run_candidate_search_crew")

        async def _run() -> dict:
            outcome = await run_candidate_search_crew(**tool_input)
            return outcome.model_dump(mode="json")

        job_store.start(job.id, _run())
        return {"job_id": job.id, "status": "started"}

    if name == "scrape_linkedin_profile":
        job = job_store.create(kind="scrape_linkedin_profile")
        job_store.start(job.id, scraping.scrape_profile(tool_input["url"]))
        return {"job_id": job.id, "status": "started"}

    if name == "scrape_company":
        job = job_store.create(kind="scrape_company")
        job_store.start(job.id, scraping.scrape_company(tool_input["url"]))
        return {"job_id": job.id, "status": "started"}

    if name == "scrape_company_posts":
        job = job_store.create(kind="scrape_company_posts")

        async def _run_posts() -> dict:
            posts = await scraping.scrape_company_posts(tool_input["url"], limit=tool_input.get("limit", 5))
            return {"posts": posts}

        job_store.start(job.id, _run_posts())
        return {"job_id": job.id, "status": "started"}

    if name == "search_jobs":
        job = job_store.create(kind="search_jobs")

        async def _run_jobs() -> dict:
            jobs = await scraping.search_jobs(
                tool_input["keywords"], tool_input["location"], limit=tool_input.get("limit", 5)
            )
            return {"jobs": jobs}

        job_store.start(job.id, _run_jobs())
        return {"job_id": job.id, "status": "started"}

    if name == "check_session_status":
        return scraping.check_session_status()

    if name == "start_login_flow":
        job = job_store.create(kind="start_login_flow")
        job_store.start(job.id, scraping.start_login_flow())
        return {"job_id": job.id, "status": "started"}

    if name == "export_candidate_subset":
        urls = tool_input["linkedin_urls"]
        label = tool_input.get("label", "subset")
        candidates = [last_results[u] for u in urls if u in last_results]
        if not candidates:
            return {"error": "None of the given linkedin_urls match candidates from this conversation."}
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:40] or "subset"
        output_path = f"candidates/chat_{safe_label}.xlsx"
        excel_path = export_candidates_to_excel(candidates, output_path)
        return {"excel_path": str(excel_path), "count": len(candidates)}

    return {"error": f"Unknown tool: {name}"}
