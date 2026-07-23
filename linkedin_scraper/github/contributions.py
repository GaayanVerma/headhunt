"""Fetch, normalize, and derive metrics for a candidate's public GitHub
contribution activity (commits/PRs/reviews/issues), across own/org/external
repositories. GraphQL-only (contributionsCollection has no REST equivalent).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .client import GitHubClient
from .queries import CONTRIBUTIONS_QUERY
from ..core.exceptions import NetworkError, RateLimitError
from ..models.contributions import (
    ContributedRepository,
    ContributionFacts,
    ContributionLimitations,
    DerivedContributionMetrics,
)

logger = logging.getLogger(__name__)

DEFAULT_CONTRIBUTION_YEARS = 2


class ContributionFetcher:
    def __init__(self, client: GitHubClient):
        self.client = client

    async def fetch(self, username: str, years: int = DEFAULT_CONTRIBUTION_YEARS) -> Dict[str, Any]:
        """Issues `years` sequential 1-year GraphQL windows ending at now, and
        merges them into one raw bundle. Returns {"windows": [...], "rate_limited": bool}."""
        windows: List[Dict[str, Any]] = []
        rate_limited = False
        now = datetime.now(timezone.utc)

        for i in range(years):
            window_to = now - timedelta(days=365 * i)
            window_from = window_to - timedelta(days=365)
            try:
                data = await self.client.graphql(
                    CONTRIBUTIONS_QUERY,
                    {
                        "login": username,
                        "from": window_from.isoformat(),
                        "to": window_to.isoformat(),
                    },
                )
            except RateLimitError:
                rate_limited = True
                break
            except NetworkError as e:
                logger.debug(f"contributions window fetch failed for {username}: {e}")
                continue

            user = data.get("user")
            if user is None:
                break
            windows.append(user.get("contributionsCollection") or {})

        return {"windows": windows, "rate_limited": rate_limited}


def _classify_repo(owner_login: str, login: str, org_logins: List[str]) -> Dict[str, bool]:
    is_own = owner_login == login
    is_org = (not is_own) and owner_login in org_logins
    is_external = not is_own and not is_org
    return {"is_own_repo": is_own, "is_org_repo": is_org, "is_external_repo": is_external}


def normalize_contributions(
    raw: Dict[str, Any], login: str, org_logins: List[str]
) -> ContributionFacts:
    windows = raw.get("windows") or []
    by_repo: Dict[str, ContributedRepository] = {}

    total_commits = 0
    total_prs = 0
    total_reviews = 0
    total_issues = 0
    total_repo_contribs = 0
    period_from: Optional[datetime] = None
    period_to: Optional[datetime] = None
    truncated = False

    for window in windows:
        total_commits += window.get("totalCommitContributions", 0) or 0
        total_prs += window.get("totalPullRequestContributions", 0) or 0
        total_reviews += window.get("totalPullRequestReviewContributions", 0) or 0
        total_issues += window.get("totalIssueContributions", 0) or 0
        total_repo_contribs += window.get("totalRepositoryContributions", 0) or 0

        started = window.get("startedAt")
        ended = window.get("endedAt")
        if started:
            started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            period_from = min(period_from, started_dt) if period_from else started_dt
        if ended:
            ended_dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            period_to = max(period_to, ended_dt) if period_to else ended_dt

        for entry in window.get("commitContributionsByRepository", []) or []:
            _merge_repo_entry(by_repo, entry, login, org_logins, field="commit_contributions")
        for entry in window.get("pullRequestContributionsByRepository", []) or []:
            _merge_repo_entry(by_repo, entry, login, org_logins, field="pull_request_contributions")
            nodes = ((entry.get("contributions") or {}).get("nodes")) or []
            if nodes:
                repo_name = ((entry.get("repository") or {}).get("nameWithOwner"))
                pr_created = (nodes[0].get("pullRequest") or {}).get("createdAt")
                if repo_name and pr_created and repo_name in by_repo:
                    dt = datetime.fromisoformat(pr_created.replace("Z", "+00:00"))
                    _update_recency(by_repo[repo_name], dt)
        for entry in window.get("pullRequestReviewContributionsByRepository", []) or []:
            _merge_repo_entry(by_repo, entry, login, org_logins, field="pull_request_review_contributions")
        for entry in window.get("issueContributionsByRepository", []) or []:
            _merge_repo_entry(by_repo, entry, login, org_logins, field="issue_contributions")

        for key in (
            "commitContributionsByRepository", "pullRequestContributionsByRepository",
            "pullRequestReviewContributionsByRepository", "issueContributionsByRepository",
        ):
            if len(window.get(key) or []) >= 100:
                truncated = True

    contributed_repos = list(by_repo.values())
    external_repos = [r.repo_full_name for r in contributed_repos if r.is_external_repo]

    limitations = ContributionLimitations(
        partial_fetch=raw.get("rate_limited", False),
        rate_limited=raw.get("rate_limited", False),
        by_repository_pagination_truncated=truncated,
        reason="rate_limited" if raw.get("rate_limited") else None,
        notes=[
            f"Contribution data assembled from {len(windows)} sequential 1-year GraphQL windows."
        ] if windows else ["No contribution windows were successfully fetched."],
    )

    return ContributionFacts(
        login=login,
        contribution_period_from=period_from,
        contribution_period_to=period_to,
        total_commit_contributions=total_commits,
        total_pull_request_contributions=total_prs,
        total_pull_request_review_contributions=total_reviews,
        total_issue_contributions=total_issues,
        total_repository_contributions=total_repo_contribs,
        contributed_repositories=contributed_repos,
        external_open_source_repositories=external_repos,
        limitations=limitations,
    )


def _merge_repo_entry(
    by_repo: Dict[str, ContributedRepository],
    entry: Dict[str, Any],
    login: str,
    org_logins: List[str],
    field: str,
) -> None:
    repository = entry.get("repository") or {}
    repo_full_name = repository.get("nameWithOwner")
    if not repo_full_name:
        return
    owner_login = (repository.get("owner") or {}).get("login", "")
    count = (entry.get("contributions") or {}).get("totalCount", 0) or 0

    if repo_full_name not in by_repo:
        classification = _classify_repo(owner_login, login, org_logins)
        by_repo[repo_full_name] = ContributedRepository(
            repo_full_name=repo_full_name,
            owner_login=owner_login,
            primary_language=(repository.get("primaryLanguage") or {}).get("name"),
            **classification,
        )
    current = getattr(by_repo[repo_full_name], field)
    setattr(by_repo[repo_full_name], field, current + count)


def _update_recency(repo: ContributedRepository, dt: datetime) -> None:
    if repo.first_contribution_at is None or dt < repo.first_contribution_at:
        repo.first_contribution_at = dt
    if repo.last_contribution_at is None or dt > repo.last_contribution_at:
        repo.last_contribution_at = dt


def compute_contribution_metrics(facts: ContributionFacts) -> DerivedContributionMetrics:
    """Pure function, same discipline as features.compute_aggregate_features:
    ratios, breadth counts, consistency/recency buckets, notable_gaps."""
    repos = facts.contributed_repositories
    total = len(repos)
    own = sum(1 for r in repos if r.is_own_repo)
    org = sum(1 for r in repos if r.is_org_repo)
    external = sum(1 for r in repos if r.is_external_repo)

    external_ratio = external / total if total else 0.0

    total_contribs = (
        facts.total_commit_contributions
        + facts.total_pull_request_contributions
        + facts.total_pull_request_review_contributions
        + facts.total_issue_contributions
    )
    external_contribs = sum(
        r.commit_contributions + r.pull_request_contributions
        + r.pull_request_review_contributions + r.issue_contributions
        for r in repos if r.is_external_repo
    )
    external_share = external_contribs / total_contribs if total_contribs else 0.0

    review_to_pr_ratio = (
        facts.total_pull_request_review_contributions / facts.total_pull_request_contributions
        if facts.total_pull_request_contributions else None
    )

    consistency = _consistency_bucket(facts)
    recency = _recency_bucket(facts)

    ecosystem_breadth = len({
        r.primary_language for r in repos if r.is_external_repo and r.primary_language
    })

    gaps = []
    if external == 0:
        gaps.append("no_external_oss_contributions_detected")
    if total_contribs == 0:
        gaps.append("no_public_contribution_activity_detected")

    return DerivedContributionMetrics(
        total_contributed_repos_count=total,
        own_repos_count=own,
        org_repos_count=org,
        external_repos_count=external,
        external_repo_ratio=round(external_ratio, 3),
        external_contribution_share=round(external_share, 3),
        review_to_pr_ratio=round(review_to_pr_ratio, 3) if review_to_pr_ratio is not None else None,
        contribution_consistency=consistency,
        contribution_recency=recency,
        ecosystem_breadth_count=ecosystem_breadth,
        notable_gaps=gaps,
    )


def _consistency_bucket(facts: ContributionFacts) -> str:
    if not facts.contribution_period_from or not facts.contribution_period_to:
        return "UNKNOWN"
    total = (
        facts.total_commit_contributions
        + facts.total_pull_request_contributions
        + facts.total_pull_request_review_contributions
        + facts.total_issue_contributions
    )
    months = max(1, (facts.contribution_period_to - facts.contribution_period_from).days // 30)
    monthly_avg = total / months
    if monthly_avg == 0:
        return "SPARSE"
    if monthly_avg < 2:
        return "OCCASIONAL"
    return "REGULAR"


def _recency_bucket(facts: ContributionFacts) -> str:
    last_dates = [r.last_contribution_at for r in facts.contributed_repositories if r.last_contribution_at]
    if not last_dates:
        return "UNKNOWN"
    most_recent = max(last_dates)
    days_since = (datetime.now(timezone.utc) - most_recent).days
    if days_since <= 30:
        return "ACTIVE_30D"
    if days_since <= 90:
        return "ACTIVE_90D"
    if days_since <= 365:
        return "ACTIVE_365D"
    return "STALE"
