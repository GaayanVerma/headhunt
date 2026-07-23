"""Public entrypoint: GitHub URL -> normalized, LLM-ready GitHubAnalysisResult."""

import logging
from datetime import datetime, timezone
from typing import Optional

from .client import GitHubClient
from .fetcher import GitHubProfileFetcher, HYGIENE_TOP_K, MAX_REPOS
from .normalizer import normalize_profile, normalize_repositories
from .features import compute_aggregate_features
from .resolver import resolve_github_username
from .snapshot import build_llm_snapshot
from ..callbacks import ProgressCallback, SilentCallback
from ..models.github import (
    GitHubAnalysisResult,
    Limitations,
    ParserMetadata,
    SourceMetadata,
)

logger = logging.getLogger(__name__)

ANALYZER_VERSION = "1.0.0"


class GitHubAnalyzer:
    """Fetch, normalize, and summarize a candidate's public GitHub presence.

    This does not subclass BaseScraper: ingestion here is pure async HTTP
    (GraphQL + REST), with no Playwright page involved.
    """

    def __init__(self, token: Optional[str] = None, callback: Optional[ProgressCallback] = None):
        self.token = token
        self.callback = callback or SilentCallback()

    async def analyze(self, github_url: str) -> GitHubAnalysisResult:
        await self.callback.on_start("github", github_url)
        try:
            result = await self._analyze(github_url)
            await self.callback.on_complete("github", result)
            return result
        except Exception as e:
            await self.callback.on_error(e)
            raise

    async def _analyze(self, github_url: str) -> GitHubAnalysisResult:
        await self.callback.on_progress("Resolving GitHub username", 5)
        username = resolve_github_username(github_url)

        fetched_at = datetime.now(timezone.utc)
        source_metadata = SourceMetadata(
            input_url_raw=github_url,
            resolved_username=username,
            fetched_at=fetched_at,
            api_layers_used=["graphql"],
            authenticated=self.token is not None,
        )

        if username is None:
            return GitHubAnalysisResult(
                source_metadata=source_metadata,
                parser_metadata=ParserMetadata(analyzer_version=ANALYZER_VERSION),
                limitations=Limitations(
                    profile_not_found=True,
                    reason="could_not_resolve_username",
                    notes=[f"Input '{github_url}' did not resolve to a GitHub profile path."],
                ),
            )

        async with GitHubClient(token=self.token) as client:
            fetcher = GitHubProfileFetcher(client)

            await self.callback.on_progress(f"Fetching profile + repos for {username}", 20)
            raw = await fetcher.fetch(username)

            source_metadata.account_type = raw["account_type"]
            if raw.get("used_rest_fallback"):
                source_metadata.api_layers_used = ["rest"]
            elif raw["hygiene_by_repo_id"]:
                source_metadata.api_layers_used.append("rest")

            parser_metadata = ParserMetadata(
                analyzer_version=ANALYZER_VERSION,
                graphql_query_cost=client.last_graphql_query_cost,
                rate_limit_remaining_after=client.graphql_rate_limit_remaining,
                repos_fetched=len(raw["repo_nodes"]),
                repos_hygiene_checked=len(raw["hygiene_by_repo_id"]),
                repos_capped=raw["repos_truncated"],
            )

            if raw["user"] is None:
                return GitHubAnalysisResult(
                    source_metadata=source_metadata,
                    parser_metadata=parser_metadata,
                    limitations=Limitations(
                        profile_not_found=(raw["account_type"] == "NOT_FOUND"),
                        rate_limited=raw["rate_limited"],
                        reason="profile_not_found" if raw["account_type"] == "NOT_FOUND" else "account_is_organization",
                        notes=(
                            ["No GitHub user or organization found for this login."]
                            if raw["account_type"] == "NOT_FOUND"
                            else ["Resolved login is a GitHub organization account, not an individual candidate."]
                        ),
                    ),
                )

            await self.callback.on_progress("Normalizing profile and repositories", 55)
            profile = normalize_profile(raw["user"])
            repos = normalize_repositories(raw["repo_nodes"], raw["hygiene_by_repo_id"])

            await self.callback.on_progress("Computing aggregate features", 75)
            aggregates = compute_aggregate_features(repos, profile)

            await self.callback.on_progress("Building LLM snapshot", 90)
            llm_snapshot = build_llm_snapshot(profile, repos, aggregates)

            hygiene_ratio = (
                parser_metadata.repos_hygiene_checked / parser_metadata.repos_fetched
                if parser_metadata.repos_fetched
                else 0.0
            )
            used_rest_fallback = raw.get("used_rest_fallback", False)
            limitations = Limitations(
                rate_limited=raw["rate_limited"],
                partial_fetch=raw["rate_limited"] or used_rest_fallback,
                repos_truncated=raw["repos_truncated"],
                hygiene_signals_checked_ratio=round(hygiene_ratio, 3),
                no_public_activity=(aggregates.original_repos_count == 0),
                reason="unauthenticated_rate_limit" if used_rest_fallback else None,
                notes=self._build_notes(raw, parser_metadata),
            )

            await self.callback.on_progress("Done", 100)
            return GitHubAnalysisResult(
                source_metadata=source_metadata,
                parser_metadata=parser_metadata,
                profile=profile,
                repositories=repos,
                aggregate_features=aggregates,
                llm_snapshot=llm_snapshot,
                limitations=limitations,
            )

    def _build_notes(self, raw: dict, parser_metadata: ParserMetadata) -> list:
        notes = [
            "Contribution calendar reflects only activity visible to an unauthenticated "
            "GitHub viewer; private-repo contributions are excluded by GitHub itself, "
            "not by this pipeline.",
        ]
        if parser_metadata.repos_fetched > HYGIENE_TOP_K:
            notes.append(
                f"Hygiene signals (CI/tests/docker/lint/manifest/readme) were only checked "
                f"for the {parser_metadata.repos_hygiene_checked} most-relevant repos "
                f"(recency + stars), not all {parser_metadata.repos_fetched} fetched repos."
            )
        if parser_metadata.repos_capped:
            notes.append(f"Repository fetch capped at {MAX_REPOS}; some repos were not analyzed.")
        if raw.get("used_rest_fallback"):
            notes.append(
                "No GitHub token configured (or GraphQL was unavailable): fell back to "
                "unauthenticated REST, limited to the 30 most recently pushed repos, "
                "with no hygiene (CI/tests/docker/lint/readme) signals fetched and no "
                "per-repo language breakdown or release data."
            )
        return notes
