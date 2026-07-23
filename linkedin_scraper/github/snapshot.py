"""Builds the compact, token-efficient LLM snapshot from facts + aggregates."""

from datetime import datetime, timezone
from typing import List, Optional

from ..models.ai_insights import CandidateLLMSnapshot, LLMRepoInsights, RepoInsight
from ..models.contributions import DerivedContributionMetrics
from ..models.github import (
    AggregateFeatures,
    EvidenceRepoSnapshot,
    GitHubProfile,
    LLMSnapshot,
    Repository,
)

_TOP_REPO_INSIGHTS_N = 5


def build_llm_snapshot(
    profile: GitHubProfile,
    repos: List[Repository],
    aggregates: AggregateFeatures,
) -> LLMSnapshot:
    repos_by_id = {r.id: r for r in repos}
    evidence = [
        _to_evidence_snapshot(repos_by_id[repo_id])
        for repo_id in aggregates.top_evidence_repos
        if repo_id in repos_by_id
    ]

    account_age_years = (
        round(aggregates.account_age_days / 365.25, 1) if aggregates.account_age_days else None
    )

    return LLMSnapshot(
        login=profile.login,
        account_age_years=account_age_years,
        public_repos=profile.public_repos_count,
        original_repos=aggregates.original_repos_count,
        followers=profile.followers_count,
        top_languages=[lang.language for lang in aggregates.top_languages[:3]],
        active_repos_90d=aggregates.active_repos_90d,
        documentation_coverage_ratio=aggregates.documentation_coverage_ratio,
        testing_coverage_ratio=aggregates.testing_coverage_ratio,
        ci_coverage_ratio=aggregates.ci_coverage_ratio,
        collaboration_repo_count=aggregates.collaboration_repo_count,
        top_evidence_repos=evidence,
        notable_gaps=_notable_gaps(aggregates),
    )


def _to_evidence_snapshot(repo: Repository) -> EvidenceRepoSnapshot:
    return EvidenceRepoSnapshot(
        name=repo.name,
        description=repo.description,
        stars=repo.stars,
        language=repo.primary_language,
        last_pushed=repo.pushed_at.date().isoformat() if repo.pushed_at else None,
        has_tests=repo.has_tests,
        has_ci=repo.has_ci,
        readme_present=repo.readme_present,
        repo_type=repo.repo_type_guess,
    )


def _notable_gaps(aggregates: AggregateFeatures) -> List[str]:
    gaps = []
    if aggregates.active_repos_90d == 0:
        gaps.append("no_recent_activity_90d")
    if aggregates.testing_coverage_ratio == 0.0 and aggregates.original_repos_count > 0:
        gaps.append("no_detected_test_coverage")
    if aggregates.ci_coverage_ratio == 0.0 and aggregates.original_repos_count > 0:
        gaps.append("no_detected_ci")
    if aggregates.original_repos_count == 0:
        gaps.append("no_original_repos_detected")
    return gaps


def build_candidate_llm_snapshot(
    login: str,
    github_llm_snapshot: LLMSnapshot,
    llm_repo_insights: LLMRepoInsights,
    derived_contribution_metrics: Optional[DerivedContributionMetrics],
) -> CandidateLLMSnapshot:
    """Layer 6: compact combined snapshot for a downstream consuming stage.
    Still non-judgmental - no verdict, no hire/no-hire, no single score."""
    top_insights = _rank_repo_insights(llm_repo_insights.insights)[:_TOP_REPO_INSIGHTS_N]

    combined_gaps = list(github_llm_snapshot.notable_gaps)
    if derived_contribution_metrics:
        for gap in derived_contribution_metrics.notable_gaps:
            if gap not in combined_gaps:
                combined_gaps.append(gap)

    notes = [
        f"Only {llm_repo_insights.limitations.repos_analyzed_count} of "
        f"{llm_repo_insights.limitations.repos_analyzed_count + llm_repo_insights.limitations.repos_skipped_count} "
        f"repos received LLM-generated code insights.",
        "Contribution data covers only a bounded recent window and excludes private-repo activity.",
        "This snapshot contains no hiring verdict or quality score; it is a factual, "
        "evidence-cited summary for a separate downstream evaluation stage.",
    ]

    return CandidateLLMSnapshot(
        login=login,
        github_facts_snapshot=github_llm_snapshot.model_dump(),
        top_repo_insights=top_insights,
        contribution_summary=(
            derived_contribution_metrics.model_dump() if derived_contribution_metrics else None
        ),
        combined_notable_gaps=combined_gaps,
        combined_limitations_notes=notes,
        generated_at=datetime.now(timezone.utc),
    )


def _rank_repo_insights(insights: List[RepoInsight]) -> List[RepoInsight]:
    """Transparent sort surfacing highest-evidence insights first - not a quality score."""

    def sort_key(insight: RepoInsight):
        return (len(insight.evidence_files), insight.confidence == "HIGH")

    return sorted(insights, key=sort_key, reverse=True)
