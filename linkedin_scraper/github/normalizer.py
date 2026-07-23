"""Pure functions mapping raw GraphQL/REST payloads to normalized fact models."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import hygiene
from ..models.github import GitHubProfile, LanguageBytes, Repository

_ACTIVE_30D = 30
_ACTIVE_90D = 90
_ACTIVE_365D = 365


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_profile(user: Dict[str, Any]) -> GitHubProfile:
    contributions = (
        (user.get("contributionsCollection") or {}).get("contributionCalendar") or {}
    ).get("totalContributions")

    return GitHubProfile(
        login=user["login"],
        name=user.get("name"),
        bio=user.get("bio"),
        company=user.get("company"),
        location=user.get("location"),
        website_url=user.get("websiteUrl"),
        email=user.get("email"),
        twitter_username=user.get("twitterUsername"),
        followers_count=(user.get("followers") or {}).get("totalCount", 0),
        following_count=(user.get("following") or {}).get("totalCount", 0),
        public_repos_count=(user.get("repositories") or {}).get("totalCount", 0),
        account_created_at=_parse_dt(user.get("createdAt")),
        avatar_url=user.get("avatarUrl"),
        is_hireable=user.get("isHireable"),
        organizations=[o["login"] for o in (user.get("organizations") or {}).get("nodes", [])],
        public_contribution_calendar_total=contributions,
    )


def _commit_activity_proxy(days_since_last_push: Optional[int]) -> str:
    if days_since_last_push is None:
        return "UNKNOWN"
    if days_since_last_push <= _ACTIVE_30D:
        return "ACTIVE_30D"
    if days_since_last_push <= _ACTIVE_90D:
        return "ACTIVE_90D"
    if days_since_last_push <= _ACTIVE_365D:
        return "ACTIVE_365D"
    return "STALE"


def normalize_repository(node: Dict[str, Any], hygiene_signals: Optional[Dict[str, Any]]) -> Repository:
    now = datetime.now(timezone.utc)
    created_at = _parse_dt(node.get("createdAt"))
    updated_at = _parse_dt(node.get("updatedAt"))
    pushed_at = _parse_dt(node.get("pushedAt"))

    repo_age_days = (now - created_at).days if created_at else None
    days_since_last_push = (now - pushed_at).days if pushed_at else None

    languages = [
        LanguageBytes(language=edge["node"]["name"], bytes=edge["size"])
        for edge in (node.get("languages") or {}).get("edges", [])
    ]
    topics = [t["topic"]["name"] for t in (node.get("repositoryTopics") or {}).get("nodes", [])]

    is_fork = node.get("isFork", False)
    is_template = node.get("isTemplate", False)
    description = node.get("description") or ""
    repo_type_guess = hygiene.guess_repo_type(node["name"], description, is_fork, is_template)
    is_mirror = node.get("mirrorUrl") is not None

    releases = node.get("releases") or {}
    latest_release = (releases.get("nodes") or [None])[0]

    hygiene_checked = hygiene_signals is not None
    file_names = hygiene_signals.get("file_names", []) if hygiene_signals else []

    default_branch_ref = node.get("defaultBranchRef") or {}
    commit_history = ((default_branch_ref.get("target") or {}).get("history") or {})
    commit_count = commit_history.get("totalCount")

    return Repository(
        id=node["id"],
        name=node["name"],
        full_name=node["nameWithOwner"],
        description=node.get("description"),
        url=node["url"],
        homepage_url=node.get("homepageUrl"),
        owner_login=node["owner"]["login"],
        owner_type=node["owner"]["__typename"].upper(),
        is_fork=is_fork,
        is_archived=node.get("isArchived", False),
        is_template=is_template,
        is_mirror=is_mirror,
        visibility=node.get("visibility", "PUBLIC"),
        default_branch=(node.get("defaultBranchRef") or {}).get("name"),
        primary_language=(node.get("primaryLanguage") or {}).get("name"),
        languages=languages,
        topics=topics,
        detected_frameworks=hygiene_signals.get("detected_frameworks", []) if hygiene_signals else [],
        license_spdx_id=(node.get("licenseInfo") or {}).get("spdxId"),
        stars=node.get("stargazerCount", 0),
        forks=node.get("forkCount", 0),
        watchers=(node.get("watchers") or {}).get("totalCount", 0),
        open_issues=(node.get("issues") or {}).get("totalCount", 0),
        size_kb=node.get("diskUsage", 0) or 0,
        created_at=created_at,
        updated_at=updated_at,
        pushed_at=pushed_at,
        releases_count=releases.get("totalCount", 0),
        latest_release_tag=latest_release.get("tagName") if latest_release else None,
        latest_release_at=_parse_dt(latest_release.get("createdAt")) if latest_release else None,
        has_issues=node.get("hasIssuesEnabled", False),
        has_projects=node.get("hasProjectsEnabled", False),
        has_wiki=node.get("hasWikiEnabled", False),
        has_pages=False,
        has_discussions=node.get("hasDiscussionsEnabled", False),
        readme_present=hygiene_signals.get("readme_present") if hygiene_signals else None,
        readme_length_chars=hygiene_signals.get("readme_length_chars") if hygiene_signals else None,
        has_ci=hygiene.has_ci(file_names) if hygiene_checked else None,
        has_tests=hygiene.has_tests(file_names) if hygiene_checked else None,
        has_docker=hygiene.has_docker(file_names) if hygiene_checked else None,
        has_lint_config=hygiene.has_lint_config(file_names) if hygiene_checked else None,
        has_package_manifest=hygiene.has_package_manifest(file_names) if hygiene_checked else None,
        contributors_count=hygiene_signals.get("contributors_count") if hygiene_signals else None,
        commit_count=commit_count,
        is_single_commit=commit_count == 1,
        repo_age_days=repo_age_days,
        days_since_last_push=days_since_last_push,
        commit_activity_proxy=_commit_activity_proxy(days_since_last_push),
        repo_type_guess=repo_type_guess,
        is_likely_portfolio_demo=hygiene.guess_is_portfolio_demo(
            node.get("homepageUrl") or "", topics, node["name"]
        ),
        hygiene_signals_checked=hygiene_checked,
    )


def normalize_repositories(
    repo_nodes: List[Dict[str, Any]], hygiene_by_repo_id: Dict[str, Dict[str, Any]]
) -> List[Repository]:
    return [
        normalize_repository(node, hygiene_by_repo_id.get(node["id"]))
        for node in repo_nodes
    ]
