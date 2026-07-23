"""GitHubAIAnalyzer: composes the deterministic GitHubAnalyzer with two new,
best-effort stages - LLM-generated repository insights and contribution
analysis - without modifying GitHubAnalyzer's behavior or dependencies.

Kept as a separate orchestrator (not a flag on GitHubAnalyzer.analyze())
because AI insight generation has a materially different reliability/cost/
latency profile (LLM calls, retries on malformed JSON, per-repo file fetch).
An LLM outage here must never fail the deterministic pipeline.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from .analyzer import GitHubAnalyzer
from .client import GitHubClient
from .contributions import ContributionFetcher, compute_contribution_metrics, normalize_contributions
from .repo_analyzer import (
    compute_docstring_density,
    compute_test_to_source_file_ratio,
    fetch_file_contents,
    fetch_repo_tree,
    select_files_for_analysis,
)
from .snapshot import build_candidate_llm_snapshot
from ..callbacks import ProgressCallback, SilentCallback
from ..core.auth import load_anthropic_key_from_env, load_github_token_from_env
from ..llm import AnthropicLLMClient, LLMClient, LLMResponseParsingError
from ..llm.json_parsing import complete_with_json_retry
from ..llm.mermaid import render_sequence_diagram
from ..llm.prompts import REPO_INSIGHT_SYSTEM_PROMPT, render_repo_insight_user_prompt
from ..models.ai_insights import (
    CandidateGitHubAIResult,
    CodeQualitySignals,
    EvidenceFileRef,
    LLMRepoInsights,
    LLMRepoInsightsLimitations,
    RepoInsight,
    WorkflowStep,
)
from ..models.contributions import ContributionFacts, DerivedContributionMetrics
from ..models.github import GitHubAnalysisResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_REPOS_FOR_LLM_INSIGHTS = 5
DEFAULT_CONTRIBUTION_YEARS = 2


class GitHubAIAnalyzer:
    """Orchestrates the deterministic GitHubAnalyzer plus AI-assisted repo
    insight generation and contribution analysis."""

    def __init__(
        self,
        github_token: Optional[str] = None,
        llm_client: Optional[LLMClient] = None,
        callback: Optional[ProgressCallback] = None,
        include_repo_insights: bool = True,
        include_contributions: bool = True,
        max_repos_for_llm_insights: int = DEFAULT_MAX_REPOS_FOR_LLM_INSIGHTS,
        contribution_years: int = DEFAULT_CONTRIBUTION_YEARS,
    ):
        self.github_token = github_token or load_github_token_from_env()
        self.callback = callback or SilentCallback()
        self.include_repo_insights = include_repo_insights
        self.include_contributions = include_contributions
        self.max_repos_for_llm_insights = max_repos_for_llm_insights
        self.contribution_years = contribution_years

        self.llm_client = llm_client
        if self.llm_client is None and self.include_repo_insights:
            api_key = load_anthropic_key_from_env()
            self.llm_client = AnthropicLLMClient(api_key=api_key) if api_key else None

    async def analyze(self, github_url: str) -> CandidateGitHubAIResult:
        await self.callback.on_start("github_ai", github_url)
        try:
            result = await self._analyze(github_url)
            await self.callback.on_complete("github_ai", result)
            return result
        except Exception as e:
            await self.callback.on_error(e)
            raise

    async def _analyze(self, github_url: str) -> CandidateGitHubAIResult:
        github_facts = await GitHubAnalyzer(token=self.github_token, callback=self.callback).analyze(github_url)

        if github_facts.profile is None:
            # Deterministic pipeline couldn't resolve a profile - degrade gracefully,
            # never attempt LLM/contribution stages against a nonexistent candidate.
            return CandidateGitHubAIResult(
                github_facts=github_facts,
                llm_repo_insights=LLMRepoInsights(),
                contribution_facts=ContributionFacts(login=github_facts.source_metadata.resolved_username or ""),
                derived_contribution_metrics=DerivedContributionMetrics(),
                candidate_llm_snapshot=build_candidate_llm_snapshot(
                    login=github_facts.source_metadata.resolved_username or "",
                    github_llm_snapshot=github_facts.llm_snapshot or _empty_llm_snapshot(),
                    llm_repo_insights=LLMRepoInsights(),
                    derived_contribution_metrics=None,
                ),
            )

        # Disabled: contribution analysis (multi-year contributionsCollection
        # GraphQL fetch) was found too heavy/noisy for the current candidate
        # summary needs - see CLAUDE.md GitHub-analysis scope. Re-enable by
        # uncommenting the block below (and restoring the include_contributions
        # constructor flag's effect).
        contribution_facts = ContributionFacts(login=github_facts.profile.login)
        derived_contribution_metrics = DerivedContributionMetrics()
        # if self.include_contributions:
        #     contribution_facts, derived_contribution_metrics = await self._fetch_contributions(github_facts)

        # Disabled: LLM-generated per-repo insights (summaries, architecture,
        # Mermaid diagrams, code-quality bands) - same reason as above. The
        # trimmed candidate summary (github/candidate_summary.py) covers what's
        # actually needed (top technologies, unlisted projects/portfolio).
        llm_repo_insights = LLMRepoInsights()
        # if self.include_repo_insights and self.llm_client is not None:
        #     llm_repo_insights = await self._generate_repo_insights(github_facts)
        # elif self.include_repo_insights:
        #     llm_repo_insights = LLMRepoInsights(
        #         limitations=LLMRepoInsightsLimitations(
        #             notes=["No Anthropic API key configured (ANTHROPIC_API_KEY); repo insight generation skipped."]
        #         )
        #     )

        candidate_llm_snapshot = build_candidate_llm_snapshot(
            login=github_facts.profile.login,
            github_llm_snapshot=github_facts.llm_snapshot or _empty_llm_snapshot(),
            llm_repo_insights=llm_repo_insights,
            derived_contribution_metrics=derived_contribution_metrics,
        )

        return CandidateGitHubAIResult(
            github_facts=github_facts,
            llm_repo_insights=llm_repo_insights,
            contribution_facts=contribution_facts,
            derived_contribution_metrics=derived_contribution_metrics,
            candidate_llm_snapshot=candidate_llm_snapshot,
        )

    # Currently unreferenced - call site disabled in _analyze() above.
    async def _fetch_contributions(self, github_facts: GitHubAnalysisResult):
        profile = github_facts.profile
        if not self.github_token:
            facts = ContributionFacts(login=profile.login)
            facts.limitations.contributions_collection_requires_auth = True
            facts.limitations.partial_fetch = True
            facts.limitations.reason = "unauthenticated_no_github_token"
            facts.limitations.notes = [
                "No GITHUB_TOKEN configured; contributionsCollection requires GraphQL "
                "authentication and was skipped entirely."
            ]
            return facts, compute_contribution_metrics(facts)

        try:
            async with GitHubClient(token=self.github_token) as client:
                await self.callback.on_progress("Fetching contribution activity", 40)
                fetcher = ContributionFetcher(client)
                raw = await fetcher.fetch(profile.login, years=self.contribution_years)
                facts = normalize_contributions(raw, profile.login, profile.organizations)
                metrics = compute_contribution_metrics(facts)
                return facts, metrics
        except Exception as e:
            logger.warning(f"Contribution fetch failed for {profile.login}: {e}")
            facts = ContributionFacts(login=profile.login)
            facts.limitations.partial_fetch = True
            facts.limitations.reason = "contribution_fetch_error"
            facts.limitations.notes = [f"Contribution fetch failed: {e}"]
            return facts, compute_contribution_metrics(facts)

    # Currently unreferenced - call site disabled in _analyze() above.
    async def _generate_repo_insights(self, github_facts: GitHubAnalysisResult) -> LLMRepoInsights:
        repos_by_id = {r.id: r for r in github_facts.repositories}
        candidate_repo_ids = github_facts.aggregate_features.top_evidence_repos[: self.max_repos_for_llm_insights]
        candidate_repos = [repos_by_id[rid] for rid in candidate_repo_ids if rid in repos_by_id]

        insights = []
        malformed_retries = 0

        async with GitHubClient(token=self.github_token) as client:
            for i, repo in enumerate(candidate_repos):
                await self.callback.on_progress(
                    f"Generating repo insight for {repo.full_name}",
                    50 + int(40 * (i + 1) / max(1, len(candidate_repos))),
                )
                insight, retries = await self._generate_one_insight(client, repo)
                insights.append(insight)
                malformed_retries += retries

        skipped_count = max(0, len(github_facts.aggregate_features.top_evidence_repos) - len(candidate_repos))
        limitations = LLMRepoInsightsLimitations(
            repos_analyzed_count=len(insights),
            repos_skipped_count=skipped_count + max(0, len(github_facts.repositories) - len(github_facts.aggregate_features.top_evidence_repos)),
            repos_skipped_reason="capped_at_max_repos_for_llm_insights",
            malformed_json_retry_count=malformed_retries,
            llm_provider="anthropic",
            llm_model=getattr(self.llm_client, "model", None),
            notes=[
                f"Only the top {len(candidate_repos)} evidence repos (by recency + hygiene) "
                f"received LLM-generated insights; the remainder have deterministic signals only."
            ],
        )
        return LLMRepoInsights(insights=insights, limitations=limitations)

    async def _generate_one_insight(self, client: GitHubClient, repo) -> "tuple[RepoInsight, int]":
        owner, _, name = repo.full_name.partition("/")
        try:
            tree = await fetch_repo_tree(client, owner, name, repo.default_branch or "HEAD")
            selected = select_files_for_analysis(tree)
            contents = await fetch_file_contents(client, owner, name, selected)

            from .repo_analyzer import detect_monorepo
            is_monorepo, subproject_paths = detect_monorepo(tree)

            files = [
                {"path": f.path, "size_bytes": f.size_bytes, "content": contents.get(f.path, "")}
                for f in selected
                if f.path in contents
            ]

            test_to_source_ratio = compute_test_to_source_file_ratio(tree)
            docstring_density = compute_docstring_density(contents)

            user_prompt = render_repo_insight_user_prompt(
                repo_full_name=repo.full_name,
                description=repo.description,
                primary_language=repo.primary_language,
                has_ci=repo.has_ci,
                has_tests=repo.has_tests,
                has_docker=repo.has_docker,
                has_lint_config=repo.has_lint_config,
                has_package_manifest=repo.has_package_manifest,
                repo_type_guess=repo.repo_type_guess,
                is_likely_portfolio_demo=repo.is_likely_portfolio_demo,
                is_monorepo_guess=is_monorepo,
                subproject_paths=subproject_paths,
                files=files,
                total_file_count_in_tree=len(tree.entries),
                files_truncated=tree.truncated or len(files) < len(selected),
                is_single_commit=repo.is_single_commit,
                test_to_source_file_ratio=test_to_source_ratio,
                docstring_density=docstring_density,
            )

            parsed, retry_count, model_name = await complete_with_json_retry(
                self.llm_client, REPO_INSIGHT_SYSTEM_PROMPT, user_prompt
            )

            workflow_steps = [
                WorkflowStep(
                    step_order=s["step_order"],
                    actor=s["actor"],
                    action=s["action"],
                    evidence_files=[
                        EvidenceFileRef(repo_full_name=repo.full_name, path=p, reason="workflow step evidence")
                        for p in s.get("evidence_paths", [])
                    ],
                )
                for s in parsed.get("workflow_steps", [])
            ]
            workflow_diagram_mermaid = render_sequence_diagram(workflow_steps) or None

            insight = RepoInsight(
                repo_id=repo.id,
                repo_full_name=repo.full_name,
                repo_summary=parsed["repo_summary"],
                workflow_summary=parsed.get("workflow_summary"),
                workflow_steps=workflow_steps,
                workflow_diagram_mermaid=workflow_diagram_mermaid,
                architecture_summary=parsed.get("architecture_summary"),
                libraries_frameworks_used=parsed.get("libraries_frameworks_used", []),
                code_quality=CodeQualitySignals(
                    readability=parsed["code_quality"].get("readability", "UNKNOWN"),
                    modularity=parsed["code_quality"].get("modularity", "UNKNOWN"),
                    project_structure_clarity=parsed["code_quality"].get("project_structure_clarity", "UNKNOWN"),
                    dependency_hygiene=parsed["code_quality"].get("dependency_hygiene", "UNKNOWN"),
                    testing_presence=parsed["code_quality"].get("testing_presence", "UNKNOWN"),
                    documentation_quality=parsed["code_quality"].get("documentation_quality", "UNKNOWN"),
                    ci_cd_presence=parsed["code_quality"].get("ci_cd_presence", "UNKNOWN"),
                    deployability=parsed["code_quality"].get("deployability", "UNKNOWN"),
                    maintainability_risk_flags=parsed["code_quality"].get("maintainability_risk_flags", []),
                    confidence=parsed["code_quality"].get("confidence", "UNKNOWN"),
                    evidence=[
                        EvidenceFileRef(repo_full_name=repo.full_name, path=e["path"], reason=e["reason"])
                        for e in parsed["code_quality"].get("evidence", [])
                    ],
                    test_to_source_file_ratio=test_to_source_ratio,
                    docstring_density=docstring_density,
                ),
                engineering_hygiene_notes=parsed.get("engineering_hygiene_notes", []),
                repo_maturity_guess=parsed.get("repo_maturity_guess", "UNKNOWN"),
                risk_flags=parsed.get("risk_flags", []),
                confidence=parsed.get("confidence", "UNKNOWN"),
                evidence_files=[
                    EvidenceFileRef(repo_full_name=repo.full_name, path=e["path"], reason=e["reason"])
                    for e in parsed.get("evidence_files", [])
                ],
                files_analyzed_count=len(files),
                files_truncated=tree.truncated or len(files) < len(selected),
                is_monorepo_guess=is_monorepo,
                llm_model_used=model_name,
                generated_at=datetime.now(timezone.utc),
            )
            return insight, retry_count
        except (LLMResponseParsingError, Exception) as e:
            logger.warning(f"Repo insight generation failed for {repo.full_name}: {e}")
            return (
                RepoInsight(
                    repo_id=repo.id,
                    repo_full_name=repo.full_name,
                    repo_summary="",
                    generation_error=str(e),
                    generated_at=datetime.now(timezone.utc),
                ),
                0,
            )


def _empty_llm_snapshot():
    from ..models.github import LLMSnapshot

    return LLMSnapshot(login="")
