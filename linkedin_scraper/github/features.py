"""Pure aggregate-feature computation over normalized repository facts."""

import statistics
from datetime import datetime, timezone
from typing import List, Optional

from ..models.github import (
    AggregateFeatures,
    FrameworkRollup,
    GitHubProfile,
    LanguageRollup,
    RepoAgeDistribution,
    Repository,
    TopicRollup,
)

_EVIDENCE_TOP_N = 5
_TOP_LANGUAGES_N = 5
_TOP_FRAMEWORKS_N = 5
# Disabled: topics rollup dropped from the trimmed candidate summary scope
# (only languages/frameworks are needed) - see github/candidate_summary.py.
# _TOP_TOPICS_N = 15


def compute_aggregate_features(
    repos: List[Repository], profile: Optional[GitHubProfile]
) -> AggregateFeatures:
    total = len(repos)
    forks = [r for r in repos if r.is_fork]
    archived = [r for r in repos if r.is_archived]
    templates = [r for r in repos if r.is_template]
    originals = [r for r in repos if r.repo_type_guess == "ORIGINAL"]

    active_30d = sum(1 for r in repos if r.commit_activity_proxy == "ACTIVE_30D")
    active_90d = sum(
        1 for r in repos if r.commit_activity_proxy in ("ACTIVE_30D", "ACTIVE_90D")
    )
    active_365d = sum(
        1 for r in repos
        if r.commit_activity_proxy in ("ACTIVE_30D", "ACTIVE_90D", "ACTIVE_365D")
    )
    stale = sum(1 for r in repos if r.commit_activity_proxy == "STALE")
    single_commit_count = sum(1 for r in repos if r.is_single_commit)

    total_stars = sum(r.stars for r in originals)
    total_forks_received = sum(r.forks for r in originals)
    median_stars = statistics.median([r.stars for r in originals]) if originals else 0.0

    top_languages = _top_languages(repos)
    # Disabled: topics rollup out of scope for the trimmed candidate summary.
    top_topics: List[TopicRollup] = []
    top_frameworks = _top_frameworks(repos)
    age_distribution = _age_distribution(repos)

    account_age_days = None
    if profile and profile.account_created_at:
        account_age_days = (datetime.now(timezone.utc) - profile.account_created_at).days

    maintained = sum(1 for r in originals if (r.days_since_last_push or 10**9) < 365)
    maintenance_ratio = maintained / len(originals) if originals else 0.0

    doc_ratio = _ratio(sum(1 for r in originals if r.readme_present), originals)
    test_ratio = _ratio(sum(1 for r in originals if r.has_tests), originals)
    ci_ratio = _ratio(sum(1 for r in originals if r.has_ci), originals)

    collaboration_count = sum(
        1 for r in repos if (r.contributors_count or 0) > 1 or r.owner_type == "ORGANIZATION"
    )
    breadth_language_count = len({lang.language for lang in top_languages})
    releases_total = sum(r.releases_count for r in originals)

    top_evidence = _rank_evidence_repos(originals)

    return AggregateFeatures(
        total_repos_fetched=total,
        original_repos_count=len(originals),
        forked_repos_count=len(forks),
        archived_repos_count=len(archived),
        template_repos_count=len(templates),
        active_repos_30d=active_30d,
        active_repos_90d=active_90d,
        active_repos_365d=active_365d,
        stale_repos_count=stale,
        single_commit_repos_count=single_commit_count,
        total_stars=total_stars,
        total_forks_received=total_forks_received,
        median_stars_per_original_repo=float(median_stars),
        top_languages=top_languages,
        top_topics=top_topics,
        top_frameworks=top_frameworks,
        repo_age_distribution=age_distribution,
        account_age_days=account_age_days,
        maintenance_consistency_score_raw=round(maintenance_ratio, 3),
        documentation_coverage_ratio=round(doc_ratio, 3),
        testing_coverage_ratio=round(test_ratio, 3),
        ci_coverage_ratio=round(ci_ratio, 3),
        collaboration_repo_count=collaboration_count,
        breadth_language_count=breadth_language_count,
        releases_shipped_total=releases_total,
        top_evidence_repos=[r.id for r in top_evidence],
        forks_excluded_count=len(forks),
        archived_excluded_count=len(archived),
        templates_excluded_count=len(templates),
    )


def _ratio(numerator: int, denom_list: List[Repository]) -> float:
    checked = [r for r in denom_list if r.hygiene_signals_checked]
    if not checked:
        return 0.0
    return numerator / len(checked)


def _top_languages(repos: List[Repository]) -> List[LanguageRollup]:
    counts: dict = {}
    for repo in repos:
        for lang in repo.languages:
            entry = counts.setdefault(lang.language, {"repo_count": 0, "total_bytes": 0})
            entry["repo_count"] += 1
            entry["total_bytes"] += lang.bytes
    ranked = sorted(counts.items(), key=lambda kv: kv[1]["total_bytes"], reverse=True)
    return [
        LanguageRollup(language=name, repo_count=v["repo_count"], total_bytes=v["total_bytes"])
        for name, v in ranked[:_TOP_LANGUAGES_N]
    ]


# Disabled: topics rollup out of scope for the trimmed candidate summary -
# see the top_topics assignment in compute_aggregate_features() above.
# def _top_topics(repos: List[Repository]) -> List[TopicRollup]:
#     counts: dict = {}
#     for repo in repos:
#         for topic in repo.topics:
#             counts[topic] = counts.get(topic, 0) + 1
#     ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
#     return [TopicRollup(topic=name, count=count) for name, count in ranked[:_TOP_TOPICS_N]]


def _top_frameworks(repos: List[Repository]) -> List[FrameworkRollup]:
    counts: dict = {}
    for repo in repos:
        for framework in repo.detected_frameworks:
            counts[framework] = counts.get(framework, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [
        FrameworkRollup(framework=name, repo_count=count)
        for name, count in ranked[:_TOP_FRAMEWORKS_N]
    ]


def _age_distribution(repos: List[Repository]) -> RepoAgeDistribution:
    ages = [r.repo_age_days for r in repos if r.repo_age_days is not None]
    if not ages:
        return RepoAgeDistribution()
    return RepoAgeDistribution(
        min_days=min(ages), max_days=max(ages), median_days=int(statistics.median(ages))
    )


def _rank_evidence_repos(originals: List[Repository]) -> List[Repository]:
    """Transparent sort for surfacing likely-strongest evidence - not a quality score."""

    def sort_key(r: Repository):
        recency_rank = -(r.days_since_last_push or 10**9)
        hygiene_score = sum([bool(r.has_tests), bool(r.has_ci), bool(r.readme_present)])
        return (hygiene_score, recency_rank)

    return sorted(originals, key=sort_key, reverse=True)[:_EVIDENCE_TOP_N]
