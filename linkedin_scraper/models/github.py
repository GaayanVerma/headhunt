"""Pydantic models for GitHub candidate analysis.

Four layers, kept separate: source/parser metadata, normalized facts
(profile + repositories), derived aggregate features, and a compact
LLM-ready snapshot. Nothing in this module renders a verdict on the
candidate - that judgment belongs to a later, separate stage.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class SourceMetadata(BaseModel):
    input_url_raw: str
    resolved_username: Optional[str] = None
    account_type: str = "NOT_FOUND"  # USER, ORGANIZATION, NOT_FOUND
    fetched_at: datetime
    api_layers_used: List[str] = []
    authenticated: bool = False


class ParserMetadata(BaseModel):
    analyzer_version: str
    graphql_query_cost: Optional[int] = None
    rate_limit_remaining_after: Optional[int] = None
    repos_fetched: int = 0
    repos_hygiene_checked: int = 0
    repos_capped: bool = False


class GitHubProfile(BaseModel):
    login: str
    name: Optional[str] = None
    bio: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    website_url: Optional[str] = None
    email: Optional[str] = None
    twitter_username: Optional[str] = None
    followers_count: int = 0
    following_count: int = 0
    public_repos_count: int = 0
    public_gists_count: Optional[int] = None
    account_created_at: Optional[datetime] = None
    avatar_url: Optional[str] = None
    is_hireable: Optional[bool] = None
    organizations: List[str] = []
    public_contribution_calendar_total: Optional[int] = None


class LanguageBytes(BaseModel):
    language: str
    bytes: int


class Repository(BaseModel):
    id: str
    name: str
    full_name: str
    description: Optional[str] = None
    url: str
    homepage_url: Optional[str] = None
    owner_login: str
    owner_type: str  # USER, ORGANIZATION

    is_fork: bool = False
    is_archived: bool = False
    is_template: bool = False
    is_mirror: bool = False
    visibility: str = "PUBLIC"
    default_branch: Optional[str] = None
    primary_language: Optional[str] = None
    languages: List[LanguageBytes] = []
    topics: List[str] = []
    detected_frameworks: List[str] = []
    license_spdx_id: Optional[str] = None

    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    size_kb: int = 0

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pushed_at: Optional[datetime] = None

    releases_count: int = 0
    latest_release_tag: Optional[str] = None
    latest_release_at: Optional[datetime] = None

    has_issues: bool = False
    has_projects: bool = False
    has_wiki: bool = False
    has_pages: bool = False
    has_discussions: bool = False

    readme_present: Optional[bool] = None
    readme_length_chars: Optional[int] = None
    has_ci: Optional[bool] = None
    has_tests: Optional[bool] = None
    has_docker: Optional[bool] = None
    has_lint_config: Optional[bool] = None
    has_package_manifest: Optional[bool] = None
    contributors_count: Optional[int] = None
    commit_count: Optional[int] = None
    is_single_commit: bool = False

    # Derived, computed once at normalization time.
    repo_age_days: Optional[int] = None
    days_since_last_push: Optional[int] = None
    commit_activity_proxy: str = "UNKNOWN"  # ACTIVE_30D/90D/365D, STALE, UNKNOWN
    repo_type_guess: str = "UNKNOWN"  # ORIGINAL, FORK, TEMPLATE_INSTANCE, TUTORIAL_FOLLOW_ALONG, MIRROR, UNKNOWN
    is_likely_portfolio_demo: bool = False
    hygiene_signals_checked: bool = False


class LanguageRollup(BaseModel):
    language: str
    repo_count: int
    total_bytes: int


class TopicRollup(BaseModel):
    topic: str
    count: int


class FrameworkRollup(BaseModel):
    framework: str
    repo_count: int


class RepoAgeDistribution(BaseModel):
    min_days: Optional[int] = None
    max_days: Optional[int] = None
    median_days: Optional[int] = None


class AggregateFeatures(BaseModel):
    total_repos_fetched: int = 0
    original_repos_count: int = 0
    forked_repos_count: int = 0
    archived_repos_count: int = 0
    template_repos_count: int = 0

    active_repos_30d: int = 0
    active_repos_90d: int = 0
    active_repos_365d: int = 0
    stale_repos_count: int = 0
    single_commit_repos_count: int = 0

    total_stars: int = 0
    total_forks_received: int = 0
    median_stars_per_original_repo: float = 0.0

    top_languages: List[LanguageRollup] = []
    top_topics: List[TopicRollup] = []
    top_frameworks: List[FrameworkRollup] = []
    repo_age_distribution: RepoAgeDistribution = RepoAgeDistribution()
    account_age_days: Optional[int] = None

    maintenance_consistency_score_raw: float = 0.0
    documentation_coverage_ratio: float = 0.0
    testing_coverage_ratio: float = 0.0
    ci_coverage_ratio: float = 0.0

    collaboration_repo_count: int = 0
    breadth_language_count: int = 0
    releases_shipped_total: int = 0

    top_evidence_repos: List[str] = []

    forks_excluded_count: int = 0
    archived_excluded_count: int = 0
    templates_excluded_count: int = 0


class EvidenceRepoSnapshot(BaseModel):
    name: str
    description: Optional[str] = None
    stars: int = 0
    language: Optional[str] = None
    last_pushed: Optional[str] = None
    has_tests: Optional[bool] = None
    has_ci: Optional[bool] = None
    readme_present: Optional[bool] = None
    repo_type: str = "UNKNOWN"


class LLMSnapshot(BaseModel):
    login: str
    account_age_years: Optional[float] = None
    public_repos: int = 0
    original_repos: int = 0
    followers: int = 0
    top_languages: List[str] = []
    active_repos_90d: int = 0
    documentation_coverage_ratio: float = 0.0
    testing_coverage_ratio: float = 0.0
    ci_coverage_ratio: float = 0.0
    collaboration_repo_count: int = 0
    top_evidence_repos: List[EvidenceRepoSnapshot] = []
    notable_gaps: List[str] = []


class Limitations(BaseModel):
    profile_not_found: bool = False
    partial_fetch: bool = False
    repos_truncated: bool = False
    rate_limited: bool = False
    hygiene_signals_checked_ratio: float = 0.0
    no_public_activity: bool = False
    contribution_calendar_may_undercount_private_activity: bool = True
    reason: Optional[str] = None
    notes: List[str] = []


class GitHubAnalysisResult(BaseModel):
    """Top-level container persisted per candidate."""

    source_metadata: SourceMetadata
    parser_metadata: ParserMetadata
    profile: Optional[GitHubProfile] = None
    repositories: List[Repository] = []
    aggregate_features: AggregateFeatures = AggregateFeatures()
    llm_snapshot: Optional[LLMSnapshot] = None
    limitations: Limitations = Limitations()

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)


class UnlistedProject(BaseModel):
    """A non-fork GitHub repository that doesn't appear to be already
    mentioned in the resume or LinkedIn profile - see
    github/candidate_summary.py:build_candidate_github_summary."""

    name: str
    url: str
    description: Optional[str] = None


class GitHubCandidateSummary(BaseModel):
    """Trimmed, decision-relevant view over a GitHubAnalysisResult: top-5
    technologies, GitHub projects not already surfaced elsewhere, and a
    personal portfolio/website link if one exists and isn't already listed.
    Deliberately narrow - replaces the old sprawling CandidateGitHubAIResult
    (LLM repo insights + contribution analysis) as the readiness/export input.
    """

    login: Optional[str] = None
    top_technologies: List[str] = []
    unlisted_projects: List[UnlistedProject] = []
    unlisted_portfolio_url: Optional[str] = None

    # Deterministic activity signals worth keeping - legitimate non-AI
    # signal, not the "bloat" the AI-generated insights/contributions were.
    original_repos_count: int = 0
    active_repos_90d: int = 0
    documentation_coverage_ratio: float = 0.0
    testing_coverage_ratio: float = 0.0
    ci_coverage_ratio: float = 0.0
    account_age_days: Optional[int] = None

    notes: List[str] = []
    """Carried through from the underlying GitHubAnalysisResult.limitations
    (e.g. profile not found, rate limited, partial fetch)."""

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)
