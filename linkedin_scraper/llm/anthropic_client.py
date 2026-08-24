"""Anthropic implementation of the provider-agnostic LLMClient interface."""

import logging
from typing import Any, Dict, List, Optional

import anthropic

from ..core.utils import retry_async
from .base import LLMClient, LLMError, LLMRateLimitError, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

_RETRYABLE_EXCEPTIONS = (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError)


class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        try:
            resp = await self._create(system_prompt, user_prompt, max_tokens, temperature)
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e

        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        return LLMResponse(
            text=text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens if resp.usage else None,
            output_tokens=resp.usage.output_tokens if resp.usage else None,
        )

    @retry_async(max_attempts=3, backoff=2.0, exceptions=_RETRYABLE_EXCEPTIONS)
    async def _create(self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float):
        return await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

    async def create_tool_turn(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> anthropic.types.Message:
        """One turn of a multi-turn, tool-using conversation.

        Unlike complete(), this is stateful (caller-managed message history)
        and can return tool_use content blocks. Returns the raw SDK message
        so the caller drives the tool_use -> dispatch -> tool_result loop
        itself - tool execution here has real side effects (headed browser
        windows, a whole CrewAI crew run) that need per-call routing to a
        job store, so a black-box agentic loop isn't the right fit.
        """
        try:
            return await self._create_tool_turn(system_prompt, messages, tools, max_tokens)
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e

    @retry_async(max_attempts=3, backoff=2.0, exceptions=_RETRYABLE_EXCEPTIONS)
    async def _create_tool_turn(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
    ):
        return await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )
