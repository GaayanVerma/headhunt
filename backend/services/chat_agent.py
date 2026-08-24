"""Conversational orchestration for the AI assistant chat.

Design (see the approved plan for the full rationale):
- Multi-turn by default: CONVERSATIONS holds each conversation's full message
  history; every call appends to it, so the user and assistant go back and
  forth freely.
- Clarify before expensive action: the system prompt tells the model to ask
  before calling run_candidate_search_crew if the ask is too thin.
- Grounded Q&A/refinement: tool results are appended to the conversation, so
  answers about candidates are always grounded in real returned data, never
  outside knowledge.
- Crew always runs to completion once started: no mid-run human-input pause
  (see run_candidate_search_crew's docstring) - all clarification happens at
  this orchestrator level, before or after a job, never mid-job.
- Long-running tools return a job_id placeholder immediately; the caller
  (backend/routers/chat.py's job-result endpoint) feeds the real result back
  in as a later turn once the job finishes, via report_job_result().
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel

from linkedin_scraper.core.auth import load_anthropic_key_from_env
from linkedin_scraper.llm.anthropic_client import AnthropicLLMClient
from linkedin_scraper.llm.base import LLMError
from linkedin_scraper.models.person_search import PersonSearchResult

from ..jobs import JOB_STORE, JobStatus
from .chat_tools import TOOLS, dispatch_tool

_llm_client: Optional[AnthropicLLMClient] = None


def get_llm_client() -> AnthropicLLMClient:
    global _llm_client
    if _llm_client is None:
        api_key = load_anthropic_key_from_env()
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set - required for the chat assistant.")
        _llm_client = AnthropicLLMClient(api_key=api_key)
    return _llm_client

SYSTEM_PROMPT = """You are a candidate-sourcing assistant for a recruiter/founder. You help find \
candidates for open roles by running searches (run_candidate_search_crew) and, when asked, \
single-target LinkedIn lookups (scrape_linkedin_profile, scrape_company, scrape_company_posts, \
search_jobs). You can also check/start a LinkedIn login session.

Ground rules:
1. Answer questions about candidates, results, or search output ONLY from tool results already \
in this conversation. Never invent or recall candidate data from outside what a tool actually \
returned. If nothing relevant has been searched yet, say so and offer to run a search.
2. run_candidate_search_crew is expensive (multiple LLM calls, possibly a real browser search). \
If the user's ask is vague or thin - missing a role/title and any skills or a JD entirely - ask \
1-2 clarifying questions in plain text before calling it. Don't ask about things you can \
reasonably default (e.g. seniority can be left unspecified).
3. After results come back, the user may want to refine. If the refinement is answerable from \
candidates already returned (e.g. "who's in Bangalore", "drop anyone without AWS"), answer or \
narrow the list in-context - don't re-run a search. Offer export_candidate_subset if they want \
that narrowed list as a downloadable file. If the refinement needs new data (e.g. a wider \
location, a different skill set), run a new search with adjusted parameters.
4. Once a search or scrape job is started, it runs to completion - you cannot pause it mid-run \
to ask the user something. Get what you need from the user before starting it.
5. Be concise. Report what a search found in plain language plus the concrete numbers (counts, \
scores) - don't just say "I found some candidates."
"""


class ChatTurnResult(BaseModel):
    conversation_id: str
    text: str
    pending_job_ids: List[str] = []


CONVERSATIONS: Dict[str, List[Dict[str, Any]]] = {}
LAST_RESULTS: Dict[str, Dict[str, PersonSearchResult]] = {}


def new_conversation_id() -> str:
    return str(uuid4())


def _ensure_conversation(conversation_id: str) -> None:
    CONVERSATIONS.setdefault(conversation_id, [])
    LAST_RESULTS.setdefault(conversation_id, {})


def _extract_text(content_blocks: List[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content_blocks if getattr(b, "type", None) == "text")


def _record_candidates(conversation_id: str, result: Dict[str, Any]) -> None:
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return
    store = LAST_RESULTS[conversation_id]
    for raw in candidates:
        try:
            candidate = PersonSearchResult.model_validate(raw)
        except Exception:
            continue
        store[candidate.linkedin_url] = candidate


async def send_message(conversation_id: str, user_text: str, llm: AnthropicLLMClient) -> ChatTurnResult:
    _ensure_conversation(conversation_id)
    messages = CONVERSATIONS[conversation_id]
    messages.append({"role": "user", "content": user_text})

    pending_job_ids: List[str] = []

    for _ in range(8):  # hard cap: a stuck tool-call loop must not spin forever
        resp = await llm.create_tool_turn(SYSTEM_PROMPT, messages, TOOLS)
        # Anthropic's documented pattern: pass the response's own content
        # blocks straight back in as the next assistant turn, unmodified -
        # the SDK serializes them correctly on the next request.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            return ChatTurnResult(
                conversation_id=conversation_id,
                text=_extract_text(resp.content),
                pending_job_ids=pending_job_ids,
            )

        tool_results = []
        round_job_ids: List[str] = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            result = await dispatch_tool(block.name, block.input, JOB_STORE, LAST_RESULTS[conversation_id])
            if "job_id" in result:
                round_job_ids.append(result["job_id"])
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str)}
            )
        messages.append({"role": "user", "content": tool_results})

        if round_job_ids:
            # At least one dispatched tool is async (a job_id placeholder, no
            # real result yet). Stop here rather than looping back into the
            # model - with nothing concrete to react to, it has no way to
            # tell "job started, wait" apart from "something went wrong, try
            # again," and will keep re-calling the tool. report_job_result()
            # resumes this conversation once the job actually finishes.
            pending_job_ids.extend(round_job_ids)
            kinds = sorted({j.kind for j in (JOB_STORE.get(jid) for jid in round_job_ids) if j is not None})
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Started: {', '.join(kinds)}. I'll follow up here once it's done.",
                }
            )
            return ChatTurnResult(
                conversation_id=conversation_id,
                text=f"Started: {', '.join(kinds)}. I'll follow up here once it's done.",
                pending_job_ids=pending_job_ids,
            )

    return ChatTurnResult(
        conversation_id=conversation_id,
        text="I made several tool calls without reaching a final answer - let's try a narrower request.",
        pending_job_ids=pending_job_ids,
    )


async def report_job_result(conversation_id: str, job_id: str, llm: AnthropicLLMClient) -> Optional[ChatTurnResult]:
    """Feed a completed job's result back into the conversation as the next turn.

    Called once the frontend's polling sees a job it started (via a
    run_candidate_search_crew/scrape_* tool call) finish - the job_id
    placeholder tool_result sent at dispatch time didn't carry real data,
    this does.
    """
    job = JOB_STORE.get(job_id)
    if job is None or job.status not in (JobStatus.succeeded, JobStatus.failed):
        return None

    _ensure_conversation(conversation_id)
    if job.status == JobStatus.succeeded and job.result:
        _record_candidates(conversation_id, job.result)
        summary = json.dumps(job.result, default=str)
        note = f"[System: job {job.id} ({job.kind}) completed successfully]\n{summary}"
    else:
        note = f"[System: job {job.id} ({job.kind}) failed]\n{job.error or 'no error detail'}"

    return await send_message(conversation_id, note, llm)


def get_last_results(conversation_id: str) -> Dict[str, PersonSearchResult]:
    return LAST_RESULTS.get(conversation_id, {})
