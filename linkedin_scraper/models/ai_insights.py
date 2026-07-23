"""Pydantic models for the LLM-assisted repository insight layer.

This is an explicitly separate, best-effort layer from the deterministic
models in github.py. Nothing here is verified fact - every claim is expected
to carry cited evidence_files, and banded fields use "UNKNOWN" rather than a
forced guess when the sampled files don't support a claim. No field in this
module renders a hiring verdict, ranking, or single quality score.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

from .github import GitHubAnalysisResult

# Bounded discrete scale, never a single scalar score.
BAND_VALUES = ("LOW", "MEDIUM", "HIGH", "UNKNOWN")


class EvidenceFileRef(BaseModel):
    repo_full_name: str
    path: str
    reason: str


class WorkflowStep(BaseModel):
    """One discrete beat of execution flow, rendered as a step in a
    Mermaid sequence diagram rather than folded into prose."""

    step_order: int
    actor: str
    action: str
    evidence_files: List[EvidenceFileRef] = []


class CodeQualitySignals(BaseModel):
    """Structured, banded - NOT a single quality score."""

    readability: str = "UNKNOWN"
    modularity: str = "UNKNOWN"
    project_structure_clarity: str = "UNKNOWN"
    dependency_hygiene: str = "UNKNOWN"
    testing_presence: str = "UNKNOWN"
    documentation_quality: str = "UNKNOWN"
    ci_cd_presence: str = "UNKNOWN"
    deployability: str = "UNKNOWN"
    maintainability_risk_flags: List[str] = []
    confidence: str = "UNKNOWN"
    evidence: List[EvidenceFileRef] = []
    # Deterministic, Python-computed anchors passed to the LLM as context -
    # never LLM-authored, so always present/trustworthy when files were sampled.
    test_to_source_file_ratio: Optional[float] = None
    docstring_density: Optional[float] = None


class RepoInsight(BaseModel):
    """One LLM-generated insight block for a single repository."""

    repo_id: str  # joins to Repository.id in github_facts
    repo_full_name: str
    repo_summary: str
    workflow_summary: Optional[str] = None  # deprecated fallback prose, kept for back-compat
    workflow_steps: List[WorkflowStep] = []
    workflow_diagram_mermaid: Optional[str] = None  # derived from workflow_steps, not LLM-authored
    architecture_summary: Optional[str] = None
    libraries_frameworks_used: List[str] = []
    code_quality: CodeQualitySignals = CodeQualitySignals()
    engineering_hygiene_notes: List[str] = []
    repo_maturity_guess: str = "UNKNOWN"  # PROTOTYPE/ACTIVE_PROJECT/MATURE/ARCHIVED_OR_ABANDONED/UNKNOWN
    risk_flags: List[str] = []
    confidence: str = "UNKNOWN"
    evidence_files: List[EvidenceFileRef] = []

    files_analyzed_count: int = 0
    files_truncated: bool = False
    is_monorepo_guess: bool = False
    llm_model_used: Optional[str] = None
    generated_at: Optional[datetime] = None
    generation_error: Optional[str] = None  # non-null => insight is partial/degraded


class LLMRepoInsightsLimitations(BaseModel):
    repos_analyzed_count: int = 0
    repos_skipped_count: int = 0
    repos_skipped_reason: Optional[str] = None
    malformed_json_retry_count: int = 0
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    notes: List[str] = []


class LLMRepoInsights(BaseModel):
    """Layer 3: llm_repo_insights."""

    insights: List[RepoInsight] = []
    limitations: LLMRepoInsightsLimitations = LLMRepoInsightsLimitations()


class CandidateLLMSnapshot(BaseModel):
    """Layer 6: compact combined snapshot for a downstream/final consuming stage.
    Still non-judgmental - no verdict, no hire/no-hire, no single score."""

    login: str
    github_facts_snapshot: dict = {}
    top_repo_insights: List[RepoInsight] = []
    contribution_summary: Optional[dict] = None
    combined_notable_gaps: List[str] = []
    combined_limitations_notes: List[str] = []
    generated_at: Optional[datetime] = None


class CandidateGitHubAIResult(BaseModel):
    """Top-level container persisted as github_ai_insights_payload.json."""

    github_facts: GitHubAnalysisResult
    llm_repo_insights: LLMRepoInsights = LLMRepoInsights()
    contribution_facts: "ContributionFacts"
    derived_contribution_metrics: "DerivedContributionMetrics"
    candidate_llm_snapshot: CandidateLLMSnapshot

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)


from .contributions import ContributionFacts, DerivedContributionMetrics  # noqa: E402

CandidateGitHubAIResult.model_rebuild()
