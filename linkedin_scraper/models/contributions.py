"""Pydantic models for open-source contribution analysis.

Two layers, kept separate from the four github.py layers: raw/normalized
contribution facts (`ContributionFacts`), and derived, non-judgmental ratios
(`DerivedContributionMetrics`). Nothing here renders a verdict - external
open-source participation is surfaced as evidence, not scored as merit.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class ContributedRepository(BaseModel):
    repo_full_name: str
    owner_login: str
    is_own_repo: bool = False
    is_org_repo: bool = False
    is_external_repo: bool = False
    primary_language: Optional[str] = None

    commit_contributions: int = 0
    pull_request_contributions: int = 0
    pull_request_review_contributions: int = 0
    issue_contributions: int = 0

    first_contribution_at: Optional[datetime] = None
    last_contribution_at: Optional[datetime] = None


class ContributionLimitations(BaseModel):
    graphql_window_limited_to_one_year: bool = True
    contributions_collection_requires_auth: bool = True
    private_contributions_excluded: bool = True
    partial_fetch: bool = False
    rate_limited: bool = False
    by_repository_pagination_truncated: bool = False
    reason: Optional[str] = None
    notes: List[str] = []


class ContributionFacts(BaseModel):
    """Layer 4: raw/normalized GitHub contribution API data."""

    login: str
    contribution_period_from: Optional[datetime] = None
    contribution_period_to: Optional[datetime] = None

    total_commit_contributions: int = 0
    total_pull_request_contributions: int = 0
    total_pull_request_review_contributions: int = 0
    total_issue_contributions: int = 0
    total_repository_contributions: int = 0

    contributed_repositories: List[ContributedRepository] = []
    external_open_source_repositories: List[str] = []

    limitations: ContributionLimitations = ContributionLimitations()


class DerivedContributionMetrics(BaseModel):
    """Layer 5: computed ratios/trends over ContributionFacts. Non-judgmental."""

    total_contributed_repos_count: int = 0
    own_repos_count: int = 0
    org_repos_count: int = 0
    external_repos_count: int = 0
    external_repo_ratio: float = 0.0
    external_contribution_share: float = 0.0
    review_to_pr_ratio: Optional[float] = None

    contribution_consistency: str = "UNKNOWN"  # SPARSE/OCCASIONAL/REGULAR/UNKNOWN
    contribution_recency: str = "UNKNOWN"  # ACTIVE_30D/90D/365D/STALE/UNKNOWN
    ecosystem_breadth_count: int = 0

    notable_gaps: List[str] = []
