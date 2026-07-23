"""ReadinessEvaluator: the founder-grade Startup Readiness Evaluation stage.

Composes Person + ResumeData + GitHubCandidateSummary (all produced upstream
by other, non-judgmental stages) into a StartupReadinessEvaluation. An LLM
outage or missing ANTHROPIC_API_KEY degrades gracefully (mirrors the
RepoInsight.generation_error pattern in github/ai_analyzer.py) - it never
raises out of evaluate().
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from ..callbacks import ProgressCallback, SilentCallback
from ..core.auth import load_anthropic_key_from_env
from ..llm import AnthropicLLMClient, LLMClient, LLMResponseParsingError
from ..models.github import GitHubCandidateSummary
from ..models.person import Person
from ..models.readiness import (
    OverallReadinessAssessment,
    ReadinessDimensionAssessment,
    ReadinessDimensions,
    StartupReadinessEvaluation,
)
from ..models.resume import ResumeData
from .parsing import complete_readiness_with_retry
from .prompts import STARTUP_READINESS_SYSTEM_PROMPT, render_readiness_user_prompt

logger = logging.getLogger(__name__)


def _degraded_evaluation(candidate_id: str, generation_error: str, message: str) -> StartupReadinessEvaluation:
    low = ReadinessDimensionAssessment(assessment=message, confidence="LOW", score=0, evidence_basis=[])
    return StartupReadinessEvaluation(
        candidate_id=candidate_id,
        overall_readiness_assessment=OverallReadinessAssessment(summary=message, confidence="LOW"),
        overall_score=0,
        recommendation="not_a_match",
        dimensions=ReadinessDimensions(
            ownership_and_proactivity=low,
            execution_credibility=low,
            drive_and_ambition=low,
            adaptability=low,
        ),
        supporting_evidence=[],
        key_strengths=[],
        key_risks_or_unknowns=[message],
        founder_takeaway=message,
        input_limitations_acknowledged=[message],
        generation_error=generation_error,
        generated_at=datetime.now(timezone.utc),
    )


class ReadinessEvaluator:
    def __init__(self, llm_client: Optional[LLMClient] = None, callback: Optional[ProgressCallback] = None):
        self.callback = callback or SilentCallback()
        self.llm_client = llm_client
        if self.llm_client is None:
            api_key = load_anthropic_key_from_env()
            self.llm_client = AnthropicLLMClient(api_key=api_key) if api_key else None

    async def evaluate(
        self,
        github_result: Optional[GitHubCandidateSummary] = None,
        person: Optional[Person] = None,
        resume: Optional[ResumeData] = None,
        candidate_id: Optional[str] = None,
    ) -> StartupReadinessEvaluation:
        resolved_id = (
            candidate_id
            or (github_result.login if github_result else None)
            or (person.name if person else None)
            or "unknown_candidate"
        )

        if self.llm_client is None:
            message = "Readiness evaluation skipped: no ANTHROPIC_API_KEY configured."
            logger.warning(message)
            return _degraded_evaluation(resolved_id, "missing_api_key", message)

        await self.callback.on_start("readiness_evaluation", resolved_id)
        try:
            user_prompt = render_readiness_user_prompt(person, resume, github_result, resolved_id)
            parsed, prose_markdown, framework_doc_markdown, model_name, retry_count = (
                await complete_readiness_with_retry(
                    self.llm_client, STARTUP_READINESS_SYSTEM_PROMPT, user_prompt
                )
            )

            dims = parsed["dimensions"]
            evaluation = StartupReadinessEvaluation(
                candidate_id=parsed.get("candidate_id") or resolved_id,
                overall_readiness_assessment=OverallReadinessAssessment(
                    **parsed["overall_readiness_assessment"]
                ),
                overall_score=parsed["overall_score"],
                recommendation=parsed["recommendation"],
                dimensions=ReadinessDimensions(
                    ownership_and_proactivity=ReadinessDimensionAssessment(**dims["ownership_and_proactivity"]),
                    execution_credibility=ReadinessDimensionAssessment(**dims["execution_credibility"]),
                    drive_and_ambition=ReadinessDimensionAssessment(**dims["drive_and_ambition"]),
                    adaptability=ReadinessDimensionAssessment(**dims["adaptability"]),
                ),
                supporting_evidence=parsed.get("supporting_evidence", []),
                key_strengths=parsed.get("key_strengths", []),
                key_risks_or_unknowns=parsed.get("key_risks_or_unknowns", []),
                founder_takeaway=parsed["founder_takeaway"],
                input_limitations_acknowledged=parsed.get("input_limitations_acknowledged", []),
                candidate_narrative=parsed.get("candidate_narrative"),
                llm_model_used=model_name,
                generated_at=datetime.now(timezone.utc),
                retry_count_used=retry_count,
                prose_report_markdown=prose_markdown,
                framework_documentation_markdown=framework_doc_markdown,
            )
            await self.callback.on_complete("readiness_evaluation", evaluation)
            return evaluation
        except (LLMResponseParsingError, Exception) as e:
            logger.warning(f"Readiness evaluation failed for {resolved_id}: {e}")
            await self.callback.on_error(e)
            return _degraded_evaluation(resolved_id, str(e), f"Readiness evaluation failed: {e}")
