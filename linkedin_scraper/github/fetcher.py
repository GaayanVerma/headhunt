"""Orchestrates raw data collection: GraphQL profile+repos, then targeted REST enrichment."""

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

from .client import GitHubClient
from .hygiene import _MANIFEST_NAMES
from .queries import PROFILE_AND_REPOS_QUERY
from .skills import _DEPENDENCY_PARSERS, extract_repo_frameworks
from ..core.exceptions import NetworkError, RateLimitError

logger = logging.getLogger(__name__)

MAX_REPOS = 300
HYGIENE_TOP_K = 40
HYGIENE_STAR_THRESHOLD = 5
REST_CONCURRENCY = 5


class GitHubProfileFetcher:
    def __init__(self, client: GitHubClient):
        self.client = client

    async def fetch(self, username: str) -> Dict[str, Any]:
        """Returns a raw bundle: {account_type, user, repo_nodes, repos_truncated,
        hygiene_by_repo_id, rate_limited, used_rest_fallback}."""
        # GraphQL requires authentication (unauthenticated requests get a 401,
        # which the client reports as a zero-remaining rate limit). Go straight
        # to the REST fallback rather than burning a retry loop on a call that
        # can never succeed unauthenticated.
        if not self.client.authenticated:
            return await self._fetch_via_rest(username)

        user, is_org, repo_nodes, repos_truncated, rate_limited = await self._fetch_profile_and_repos(username)

        if rate_limited:
            return await self._fetch_via_rest(username)

        if user is None:
            account_type = "ORGANIZATION" if is_org else "NOT_FOUND"
            return {
                "account_type": account_type,
                "user": None,
                "repo_nodes": [],
                "repos_truncated": False,
                "hygiene_by_repo_id": {},
                "rate_limited": False,
                "used_rest_fallback": False,
            }

        selected = self._select_for_hygiene_check(repo_nodes)
        hygiene_by_repo_id = await self._fetch_hygiene_signals(selected)

        return {
            "account_type": "USER",
            "user": user,
            "repo_nodes": repo_nodes,
            "repos_truncated": repos_truncated,
            "hygiene_by_repo_id": hygiene_by_repo_id,
            "rate_limited": False,
            "used_rest_fallback": False,
        }

    async def _fetch_via_rest(self, username: str) -> Dict[str, Any]:
        """Unauthenticated (or GraphQL-failed) fallback. Profile + top N repos only,
        no hygiene REST calls (60 req/hr budget is too tight to spend on them)."""
        status, user_json, _ = await self.client.rest_get(f"/users/{username}")

        if status == 404:
            return {
                "account_type": "NOT_FOUND",
                "user": None,
                "repo_nodes": [],
                "repos_truncated": False,
                "hygiene_by_repo_id": {},
                "rate_limited": False,
                "used_rest_fallback": True,
            }
        if status != 200 or user_json is None:
            return {
                "account_type": "NOT_FOUND",
                "user": None,
                "repo_nodes": [],
                "repos_truncated": False,
                "hygiene_by_repo_id": {},
                "rate_limited": True,
                "used_rest_fallback": True,
            }

        if user_json.get("type") == "Organization":
            return {
                "account_type": "ORGANIZATION",
                "user": None,
                "repo_nodes": [],
                "repos_truncated": False,
                "hygiene_by_repo_id": {},
                "rate_limited": False,
                "used_rest_fallback": True,
            }

        status, repos_json, _ = await self.client.rest_get(
            f"/users/{username}/repos", params={"sort": "pushed", "per_page": 30}
        )
        repo_list = repos_json if status == 200 and isinstance(repos_json, list) else []

        return {
            "account_type": "USER",
            "user": _rest_user_to_node(user_json),
            "repo_nodes": [_rest_repo_to_node(r) for r in repo_list],
            "repos_truncated": len(repo_list) >= 30,
            "hygiene_by_repo_id": {},
            "rate_limited": False,
            "used_rest_fallback": True,
        }

    async def _fetch_profile_and_repos(
        self, username: str
    ) -> Tuple[Optional[Dict[str, Any]], bool, List[Dict[str, Any]], bool, bool]:
        repo_nodes: List[Dict[str, Any]] = []
        cursor = None
        rate_limited = False
        user_data = None
        is_org = False

        while True:
            try:
                data = await self.client.graphql(
                    PROFILE_AND_REPOS_QUERY, {"login": username, "cursor": cursor}
                )
            except RateLimitError:
                rate_limited = True
                break

            user_data = data.get("user")
            if user_data is None:
                is_org = data.get("organization") is not None
                break

            repos_page = user_data["repositories"]
            repo_nodes.extend(repos_page["nodes"])

            page_info = repos_page["pageInfo"]
            if not page_info["hasNextPage"] or len(repo_nodes) >= MAX_REPOS:
                break
            cursor = page_info["endCursor"]

        truncated = len(repo_nodes) >= MAX_REPOS
        if truncated:
            repo_nodes = repo_nodes[:MAX_REPOS]

        return user_data, is_org, repo_nodes, truncated, rate_limited

    def _select_for_hygiene_check(self, repo_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # repo_nodes already ordered by pushed_at desc from the query.
        top_k = repo_nodes[:HYGIENE_TOP_K]
        top_k_ids = {r["id"] for r in top_k}
        starred = [
            r for r in repo_nodes[HYGIENE_TOP_K:]
            if r.get("stargazerCount", 0) > HYGIENE_STAR_THRESHOLD and r["id"] not in top_k_ids
        ]
        return top_k + starred

    async def _fetch_hygiene_signals(self, repos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        semaphore = asyncio.Semaphore(REST_CONCURRENCY)
        results: Dict[str, Dict[str, Any]] = {}

        async def fetch_one(repo: Dict[str, Any]) -> None:
            async with semaphore:
                owner = repo["owner"]["login"]
                name = repo["name"]
                results[repo["id"]] = await self._fetch_repo_hygiene(owner, name)

        await asyncio.gather(*(fetch_one(r) for r in repos))
        return results

    async def _fetch_repo_hygiene(self, owner: str, name: str) -> Dict[str, Any]:
        """Best-effort per-signal fetch. Any single failing signal (rate limit,
        oversized repo, transient error) degrades that field to None rather
        than aborting the whole repo or the pipeline."""
        file_names: List[str] = []
        readme_present = None
        readme_length = None
        contributors_count = None

        try:
            status, contents, _ = await self.client.rest_get(f"/repos/{owner}/{name}/contents/")
            if status == 200 and isinstance(contents, list):
                file_names = [entry.get("name", "") for entry in contents]
        except (NetworkError, RateLimitError) as e:
            logger.debug(f"contents fetch failed for {owner}/{name}: {e}")

        try:
            status, readme, _ = await self.client.rest_get(f"/repos/{owner}/{name}/readme")
            if status == 200 and readme:
                readme_present = True
                readme_length = readme.get("size")
            elif status == 404:
                readme_present = False
        except (NetworkError, RateLimitError) as e:
            logger.debug(f"readme fetch failed for {owner}/{name}: {e}")

        try:
            status, contributors, _ = await self.client.rest_get(
                f"/repos/{owner}/{name}/contributors", params={"per_page": 5, "anon": "false"}
            )
            if status == 200 and isinstance(contributors, list):
                contributors_count = len(contributors)
            # status == 202 (stats computing) or 404 (empty repo) -> leave as None.
        except (NetworkError, RateLimitError) as e:
            # e.g. 403 "contributor list too large" on massive repos - not fetchable at all.
            logger.debug(f"contributors fetch failed for {owner}/{name}: {e}")

        detected_frameworks = await self._fetch_detected_frameworks(owner, name, file_names)

        return {
            "file_names": file_names,
            "readme_present": readme_present,
            "readme_length_chars": readme_length,
            "contributors_count": contributors_count,
            "detected_frameworks": detected_frameworks,
        }

    async def _fetch_detected_frameworks(
        self, owner: str, name: str, file_names: List[str]
    ) -> List[str]:
        """Fetch content for any root manifest file we know how to parse, and
        derive framework/library names from it. Best-effort: a fetch or parse
        failure for one manifest just omits that file's signal."""
        manifest_files = [
            n for n in file_names
            if n.lower() in _MANIFEST_NAMES and n.lower() in _DEPENDENCY_PARSERS
        ]
        if not manifest_files:
            return []

        manifest_contents: Dict[str, str] = {}
        for file_name in manifest_files:
            try:
                status, data, _ = await self.client.rest_get(f"/repos/{owner}/{name}/contents/{file_name}")
                if status == 200 and data and data.get("content"):
                    manifest_contents[file_name] = base64.b64decode(data["content"]).decode(
                        "utf-8", errors="replace"
                    )
            except (NetworkError, RateLimitError) as e:
                logger.debug(f"manifest fetch failed for {owner}/{name}/{file_name}: {e}")

        return extract_repo_frameworks(manifest_contents)


def _rest_user_to_node(user_json: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt REST GET /users/{login} JSON into the shape normalize_profile() expects."""
    return {
        "login": user_json.get("login"),
        "name": user_json.get("name"),
        "bio": user_json.get("bio"),
        "company": user_json.get("company"),
        "location": user_json.get("location"),
        "websiteUrl": user_json.get("blog") or None,
        "email": user_json.get("email"),
        "twitterUsername": user_json.get("twitter_username"),
        "followers": {"totalCount": user_json.get("followers", 0)},
        "following": {"totalCount": user_json.get("following", 0)},
        "repositories": {"totalCount": user_json.get("public_repos", 0)},
        "createdAt": user_json.get("created_at"),
        "avatarUrl": user_json.get("avatar_url"),
        "isHireable": user_json.get("hireable"),
        "organizations": {"nodes": []},
        "contributionsCollection": {"contributionCalendar": {"totalContributions": None}},
    }


def _rest_repo_to_node(repo_json: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt REST GET /users/{login}/repos JSON into the shape normalize_repository() expects."""
    license_info = repo_json.get("license") or {}
    return {
        "id": str(repo_json.get("id")),
        "name": repo_json.get("name"),
        "nameWithOwner": repo_json.get("full_name"),
        "description": repo_json.get("description"),
        "url": repo_json.get("html_url"),
        "homepageUrl": repo_json.get("homepage"),
        "owner": {
            "login": (repo_json.get("owner") or {}).get("login"),
            "__typename": "User" if (repo_json.get("owner") or {}).get("type") == "User" else "Organization",
        },
        "isFork": repo_json.get("fork", False),
        "isArchived": repo_json.get("archived", False),
        "isTemplate": repo_json.get("is_template", False),
        "mirrorUrl": repo_json.get("mirror_url"),
        "visibility": (repo_json.get("visibility") or "public").upper(),
        "defaultBranchRef": {"name": repo_json.get("default_branch")},
        "primaryLanguage": {"name": repo_json.get("language")} if repo_json.get("language") else None,
        "languages": {"edges": []},  # not available without a second call; left empty in fallback mode
        "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in repo_json.get("topics", [])]},
        "licenseInfo": {"spdxId": license_info.get("spdx_id")} if license_info else None,
        "stargazerCount": repo_json.get("stargazers_count", 0),
        "forkCount": repo_json.get("forks_count", 0),
        "watchers": {"totalCount": repo_json.get("watchers_count", 0)},
        "issues": {"totalCount": repo_json.get("open_issues_count", 0)},
        "diskUsage": repo_json.get("size", 0),
        "createdAt": repo_json.get("created_at"),
        "updatedAt": repo_json.get("updated_at"),
        "pushedAt": repo_json.get("pushed_at"),
        "releases": {"totalCount": 0, "nodes": []},  # not available without a second call in fallback mode
        "hasIssuesEnabled": repo_json.get("has_issues", False),
        "hasProjectsEnabled": repo_json.get("has_projects", False),
        "hasWikiEnabled": repo_json.get("has_wiki", False),
        "hasDiscussionsEnabled": repo_json.get("has_discussions", False),
    }
