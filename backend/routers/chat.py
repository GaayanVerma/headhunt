"""AI assistant chat endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from linkedin_scraper.llm.base import LLMError

from ..services import chat_agent

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    conversation_id: Optional[str] = None
    text: str


class JobResultRequest(BaseModel):
    conversation_id: str
    job_id: str


@router.post("/message")
async def post_message(req: ChatMessageRequest) -> chat_agent.ChatTurnResult:
    conversation_id = req.conversation_id or chat_agent.new_conversation_id()
    try:
        llm = chat_agent.get_llm_client()
        return await chat_agent.send_message(conversation_id, req.text, llm)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/job-result")
async def post_job_result(req: JobResultRequest) -> chat_agent.ChatTurnResult:
    llm = chat_agent.get_llm_client()
    result = await chat_agent.report_job_result(req.conversation_id, req.job_id, llm)
    if result is None:
        raise HTTPException(status_code=409, detail="Job not found or not finished yet")
    return result
