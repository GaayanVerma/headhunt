"""Provider-agnostic LLM client interface.

`GitHubAIAnalyzer` and the prompt/parsing helpers depend only on this
abstract interface, never on a specific SDK. `AnthropicLLMClient` is the
only implementation today; a future provider can be swapped in via
constructor injection without touching orchestration or prompt code.
"""

from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class LLMClient(ABC):
    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        ...


class LLMError(Exception):
    """Base exception for LLM-layer failures."""


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider signals rate limiting."""


class LLMResponseParsingError(LLMError):
    """Raised when a response cannot be parsed into the expected JSON schema
    after all retries are exhausted."""
