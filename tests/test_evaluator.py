"""Unit tests for ReadinessEvaluator - fake LLM client, no network calls."""

import json

import pytest

from linkedin_scraper.evaluation.evaluator import ReadinessEvaluator
from linkedin_scraper.llm.base import LLMClient, LLMResponse
from linkedin_scraper.models.github import GitHubCandidateSummary
from linkedin_scraper.models.person import Person


def _valid_json_payload() -> dict:
    dim = {"assessment": "x", "confidence": "MEDIUM", "score": 60, "evidence_basis": ["a"]}
    return {
        "candidate_id": "jane",
        "overall_readiness_assessment": {"summary": "s", "confidence": "MEDIUM"},
        "overall_score": 60,
        "recommendation": "possible_match",
        "dimensions": {
            "ownership_and_proactivity": dim,
            "execution_credibility": dim,
            "drive_and_ambition": dim,
            "adaptability": dim,
        },
        "supporting_evidence": ["e1"],
        "key_strengths": ["strong"],
        "key_risks_or_unknowns": ["risk"],
        "founder_takeaway": "takeaway",
        "input_limitations_acknowledged": ["no github"],
        "candidate_narrative": "Backend engineer who ships fast.",
    }


def _fake_response_text() -> str:
    payload = _valid_json_payload()
    return (
        "## Startup Readiness Evaluation\nprose\n\n"
        "## Supporting Evidence\n- e1\n\n"
        "## Confidence and Limitations\n- limited\n\n"
        "## Structured Output\n```json\n" + json.dumps(payload) + "\n```\n"
        "\n## Markdown Documentation\n```markdown\n# Framework Doc\nbody\n```\n"
    )


class _FakeLLMClient(LLMClient):
    def __init__(self):
        self.last_user_prompt = None

    async def complete(self, system_prompt, user_prompt, max_tokens=4096, temperature=0.0):
        self.last_user_prompt = user_prompt
        return LLMResponse(text=_fake_response_text(), model="fake-model")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_without_github_result_does_not_raise():
    evaluator = ReadinessEvaluator(llm_client=_FakeLLMClient())
    person = Person(linkedin_url="https://linkedin.com/in/janedoe", name="Jane Doe")

    evaluation = await evaluator.evaluate(github_result=None, person=person, candidate_id="jane")

    assert evaluation.generation_error is None
    assert evaluation.overall_score == 60
    assert evaluation.candidate_narrative == "Backend engineer who ships fast."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_without_github_or_api_key_degrades_gracefully():
    evaluator = ReadinessEvaluator(llm_client=_FakeLLMClient())
    evaluator.llm_client = None  # simulate no ANTHROPIC_API_KEY configured, without a real network call

    evaluation = await evaluator.evaluate(github_result=None, candidate_id="jane")
    assert evaluation.generation_error == "missing_api_key"
    assert evaluation.overall_score == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_with_github_candidate_summary_resolves_id_from_login():
    fake_client = _FakeLLMClient()
    evaluator = ReadinessEvaluator(llm_client=fake_client)
    github_summary = GitHubCandidateSummary(login="janedoe", top_technologies=["Python", "Go"])

    evaluation = await evaluator.evaluate(github_result=github_summary)

    assert evaluation.generation_error is None
    assert "Candidate ID: janedoe" in fake_client.last_user_prompt
    assert "Top technologies: ['Python', 'Go']" in fake_client.last_user_prompt
