# GitHub Analyzer — Design Documentation

## 1. Project Overview

The GitHub Analyzer is a module in the candidate enrichment pipeline (`linkedin_scraper/github/`) that turns a GitHub profile URL — found in a resume or candidate profile — into a structured, auditable, LLM-ready dataset describing the candidate's public GitHub presence.

It sits alongside the existing pipeline stages:

- **Resume parsing** (`linkedin_scraper/resume/parser.py`) already extracts and categorizes `github_url` into `ResumeData`.
- **LinkedIn enrichment** (`linkedin_scraper/scrapers/`) fetches profile/company/job data via Playwright.
- **GitHub analyzer** (this module) fetches profile + repository data via the GitHub API (GraphQL-primary, REST-secondary) — no browser involved.

Output is persisted per-candidate (mirroring `linkedin_scraper/candidates/<Name>/candidate_profile_payload.json`) as `github_profile_payload.json`, ready to be read by a later, separate LLM evaluation stage.

## 2. Goals and Non-Goals

### Goals
- Resolve a GitHub URL (in any form the resume parser might produce) to a username.
- Fetch profile-level and repository-level data efficiently, respecting GitHub's rate limits.
- Normalize raw API data into stable, nullable-safe fact models.
- Compute derived, non-judgmental features (activity buckets, coverage ratios, rollups).
- Produce a compact snapshot suitable for injecting into LLM prompts.
- Preserve full provenance and explicit limitations/caveats for every result.

### Non-Goals
- **No final candidate scoring or verdicts.** No `quality_score`, no `is_strong_candidate`. That belongs to a separate downstream stage.
- No private repository access — public-data-first design.
- No commit-by-commit history, blame, or full file trees — too large, no LLM-snapshot value.
- No star/fork "who" lists — no signal value, pure noise.

## 3. Recommended API Strategy

**Hybrid, GraphQL-primary, REST-secondary.**

| Concern | Use |
|---|---|
| Profile + repo list + languages + topics + license + core metadata | **GraphQL** (`api.github.com/graphql`) — 1–3 round trips via cursor pagination |
| Rate-limit introspection (`rateLimit { remaining resetAt cost }`) | GraphQL, queried alongside every batch |
| Contribution calendar | GraphQL only (not available via REST) |
| README presence/size, `.github/workflows` / CI / Docker / lint / manifest detection, contributors count | **REST**, targeted per-repo calls — GraphQL doesn't expose file-tree/contents cheaply |
| Fallback when GraphQL fails or no token is configured | REST (`GET /users/{login}`, `GET /users/{login}/repos`) |

**Why hybrid, not pure GraphQL or pure REST:**
- Pure REST has an N+1 problem: languages/releases/contributors are separate calls per repo. For 300 repos that's 900+ calls.
- GraphQL collapses profile + repo core fields into 1–3 calls, but its schema doesn't expose file contents — hygiene signals (CI/tests/Docker/lint/manifest) still need targeted REST.

**Important operational finding:** GitHub's GraphQL API requires authentication — an unauthenticated GraphQL call returns `401 Bad credentials` (not a soft "public preview"). This means:
- With no `GITHUB_TOKEN`, the analyzer must skip GraphQL entirely and go straight to the REST fallback path (profile + up to 30 most-recently-pushed repos, no hygiene signals, no per-repo language/release breakdown).
- A `GITHUB_TOKEN` (no special scopes needed — this pipeline is public-data-only) is **strongly recommended**, not just a nice-to-have.

**Rate limits:** authenticated GraphQL = 5000 points/hr (cost-scored per query); authenticated REST = 5000 req/hr; unauthenticated REST = 60/hr, no GraphQL access at all.

**Pagination:** GraphQL cursor-based (`repositories(first: 50, after: $cursor)`), looping until `pageInfo.hasNextPage` is false or a hard cap (300 repos) is hit.

**Resilience:** exponential backoff on `403`/secondary rate limit and `5xx`, honoring `Retry-After`. Each hygiene REST call (contents, README, contributors) is fetched independently and degrades to `null` on failure rather than aborting the whole repo or pipeline — this matters in practice: large repos (e.g. Linux kernel-scale) return `403 "contributor list too large"` from the `/contributors` endpoint, and the pipeline must not treat that as fatal.

## 4. Ingestion Pipeline

1. **URL resolution** — `resolve_github_username(raw_url_or_handle)`. Strips scheme/`www.`/trailing slash/query/fragment, validates against `github.com/<owner>`, rejects reserved paths (`orgs`, `marketplace`, `settings`, etc.), rejects malformed handles.
2. **Existence + profile + repos fetch (single GraphQL query)** — `user(login:)` and `organization(login:)` queried together; `user` null + `organization` present → org account; both null → not found.
3. **Repo pagination loop** — follow cursors until exhausted or the 300-repo cap is hit; flag `repos_truncated` if capped.
4. **Relevance pre-filter** — before expensive per-repo REST calls, take the top 40 repos by `pushed_at` recency plus any repo with `stars > 5` outside that set. Repos outside this set keep their GraphQL-sourced fields but skip hygiene REST calls (`hygiene_signals_checked: false`).
5. **REST enrichment loop** (concurrency-capped, 5 at a time) — root `/contents/` listing, `/readme`, `/contributors?per_page=5`. Each call is independently fault-tolerant.
6. **Normalization** — raw GraphQL/REST nodes → `Repository` / `GitHubProfile` fact models; compute per-repo derived fields (`repo_age_days`, `commit_activity_proxy`, `repo_type_guess`, `is_likely_portfolio_demo`).
7. **Aggregation** — compute `AggregateFeatures` across the normalized repo set (excluding forks/archived/templates from "original work" rollups, but preserving exclusion counts).
8. **Snapshot generation** — compact `LLMSnapshot`: profile essentials, rollups, and top 5 evidence repos.
9. **Limitations assembly** — `partial_fetch`, `repos_truncated`, `rate_limited`, `hygiene_signals_checked_ratio`, `no_public_activity`, standing caveat about contribution-calendar undercounting private activity, and (when applicable) the unauthenticated-fallback note.
10. **Persist** — raw payload kept separately from normalized output; normalized+derived+snapshot written to `linkedin_scraper/candidates/<Name>/github_profile_payload.json`.
11. **Error handling** — any stage failure degrades gracefully (partial data + limitations flags); only a fully unresolvable username or profile-not-found is a hard stop.

## 5. Schema Design Principles

1. **Four strict layers, never mixed:** raw → normalized fact → derived feature → LLM snapshot.
2. **No adjectives, no verdicts.** Counts, booleans, enums, timestamps only.
3. **Null is data.** Every optional field is explicitly `null`, never omitted — stable keys across all candidates.
4. **Caveats are first-class** — a dedicated `limitations` object on every result.
5. **Hygiene flags are precomputed once at ingestion** (`has_ci`, `has_tests`, etc.) so the LLM stage never re-derives them from raw payloads.
6. **Aggregates exclude forks/archived/templates from "original work" rollups**, but exclusion counts are preserved for transparency.

## 6. Repository Signal Model

| Field | Type | Derivation | Why it matters |
|---|---|---|---|
| `id` / `node_id` | string | raw | stable key |
| `name`, `full_name` | string | raw | |
| `owner_login`, `owner_type` (`USER`\|`ORGANIZATION`) | string | raw | org repos = collaboration signal |
| `is_fork`, `is_archived`, `is_template` | bool | raw | excluded from "original work" rollups |
| `is_mirror` | bool (derived) | `mirrorUrl != null` | mirrors ≠ authored work |
| `primary_language`, `languages` | string, map | raw | breakdown, not just primary |
| `topics`, `license_spdx_id` | array, string | raw | |
| `stars`, `forks`, `watchers`, `open_issues` | int | raw | **weak signals** — flagged as such, never weighted here |
| `created_at`, `updated_at`, `pushed_at` | datetime | raw | `pushed_at` is the real activity signal (not `updated_at`) |
| `releases_count`, `latest_release_tag/at` | int, string, datetime | raw | shipping signal |
| `has_issues/projects/wiki/pages/discussions` | bool | raw | feature usage |
| `readme_present`, `readme_length_chars` | bool, int | REST | documentation proxy |
| `has_ci`, `has_tests`, `has_docker`, `has_lint_config`, `has_package_manifest` | bool\|null | REST contents listing | engineering hygiene |
| `contributors_count` | int\|null | REST (capped, best-effort) | >1 = collaboration; null if endpoint errors (e.g. oversized repo) |
| `repo_age_days`, `days_since_last_push` | int (derived) | now − created/pushed | |
| `commit_activity_proxy` | enum: `ACTIVE_30D`/`90D`/`365D`/`STALE`/`UNKNOWN` (derived) | thresholds on recency | cheap LLM-reasoning bucket |
| `repo_type_guess` | enum: `ORIGINAL`/`FORK`/`TEMPLATE_INSTANCE`/`TUTORIAL_FOLLOW_ALONG`/`MIRROR`/`UNKNOWN` (derived) | heuristic — **explicitly a guess, never asserted as fact** | |
| `is_likely_portfolio_demo` | bool (derived) | heuristic on homepage/topics/name | low-confidence, labeled as such |
| `hygiene_signals_checked` | bool | pipeline bookkeeping | makes REST-skip auditable, not silent |

**Explicitly excluded from normalized schema:** commit history, full file trees, blame, star/fork user lists, full wiki content.

## 7. Aggregate Feature Model

| Feature | Computation |
|---|---|
| `total_repos_fetched`, `original_repos_count`, `forked_repos_count`, `archived_repos_count`, `template_repos_count` | counts by category |
| `active_repos_30d/90d/365d`, `stale_repos_count` | bucketed on `commit_activity_proxy` |
| `total_stars`, `total_forks_received`, `median_stars_per_original_repo` | over `ORIGINAL` repos only |
| `top_languages` (top 8), `top_topics` (top 15) | aggregated from per-repo language bytes / topic frequency |
| `repo_age_distribution` | min/max/median over non-excluded repos |
| `account_age_days` | from profile `createdAt` |
| `maintenance_consistency_score_raw` | fraction of originals pushed within 365 days — `_raw` suffix intentional, **not a verdict** |
| `documentation_coverage_ratio`, `testing_coverage_ratio`, `ci_coverage_ratio` | hygiene-flag hit rate over originals with hygiene checked |
| `collaboration_repo_count` | repos with `contributors_count > 1` OR org-owned |
| `breadth_language_count` | distinct languages across `top_languages` |
| `releases_shipped_total` | sum of `releases_count` over originals |
| `top_evidence_repos` | top 5 by transparent, disclosed sort (recency + tests/CI/readme) — a *surfacing* sort, not a quality score |
| `forks_excluded_count`, `archived_excluded_count`, `templates_excluded_count` | transparency counters |

## 8. GraphQL Query Shape

```graphql
query CandidateGitHub($login: String!, $cursor: String) {
  rateLimit { remaining resetAt cost }
  user(login: $login) {
    login
    name
    bio
    company
    location
    websiteUrl
    email
    twitterUsername
    followers { totalCount }
    following { totalCount }
    createdAt
    avatarUrl
    isHireable
    organizations(first: 20) { nodes { login } }
    contributionsCollection {
      contributionCalendar { totalContributions }
    }
    repositories(
      first: 50
      after: $cursor
      ownerAffiliations: [OWNER]
      orderBy: {field: PUSHED_AT, direction: DESC}
      isFork: null
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        name
        nameWithOwner
        description
        url
        homepageUrl
        owner { login __typename }
        isFork
        isArchived
        isTemplate
        mirrorUrl
        visibility
        defaultBranchRef { name }
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
        repositoryTopics(first: 15) { nodes { topic { name } } }
        licenseInfo { spdxId }
        stargazerCount
        forkCount
        watchers { totalCount }
        issues(states: OPEN) { totalCount }
        diskUsage
        createdAt
        updatedAt
        pushedAt
        releases(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes { tagName createdAt }
        }
        hasIssuesEnabled
        hasProjectsEnabled
        hasWikiEnabled
        hasDiscussionsEnabled
      }
    }
  }
  organization(login: $login) {
    login
  }
}
```

Notes:
- **Do not** query `repositories(...)` twice with different arguments under the same field name in one query — GitHub's schema rejects it as a `fieldConflict` error. `totalCount` must live on the same paginated `repositories` field used for the node list.
- Paginate by re-issuing with `$cursor = pageInfo.endCursor` until `hasNextPage` is false or the 300-repo cap is hit.
- `isFork: null` intentionally fetches both forks and originals in one pass — filtering happens in the normalizer, not at query time, so exclusion counts stay accurate.
- This query **requires** an `Authorization: Bearer <token>` header; GitHub's GraphQL endpoint returns `401` for unauthenticated requests.

## 9. REST Fallback Endpoints

Used for what GraphQL can't give cheaply (targeted at the relevance-filtered repo subset), and as the entire data path when no token is configured.

```
GET /users/{login}
GET /users/{login}/repos?sort=pushed&per_page=30        # unauthenticated fallback repo list
GET /repos/{owner}/{repo}/languages
GET /repos/{owner}/{repo}/contents/                       # root listing → CI/Docker/tests/lint/manifest detection
GET /repos/{owner}/{repo}/readme
GET /repos/{owner}/{repo}/releases?per_page=1
GET /repos/{owner}/{repo}/contributors?per_page=5&anon=false
GET /repos/{owner}/{repo}
GET /rate_limit
```

Behavioral notes learned from live testing:
- `/contributors` can return `403 "history or contributor list is too large"` for very large repos — treat as a soft failure, set `contributors_count: null`, do not abort the repo or pipeline.
- `/contributors` and similar stats endpoints may also return `202` while GitHub computes stats — retry once, else `null`.
- Unauthenticated fallback path (no `GITHUB_TOKEN`): profile via `GET /users/{login}` + repos via `GET /users/{login}/repos?sort=pushed&per_page=30`; hygiene REST calls are skipped entirely (60 req/hr budget is too tight); `limitations.partial_fetch = true`, `limitations.reason = "unauthenticated_rate_limit"`.

## 10. Python Implementation Architecture

```
linkedin_scraper/
  github/
    __init__.py
    client.py       # GitHubClient: httpx.AsyncClient wrapper, GraphQL + REST,
                     #   auth header injection, rate-limit tracking, @retry_async
    resolver.py      # resolve_github_username(url_or_handle) -> str | None
    queries.py        # GraphQL query strings
    fetcher.py         # GitHubProfileFetcher: pagination, relevance filter,
                        #   REST hygiene enrichment, unauthenticated REST fallback
    hygiene.py           # pure has_ci/has_tests/has_docker/has_lint_config/
                          #   has_package_manifest/repo_type_guess detectors
    normalizer.py          # raw -> Repository / GitHubProfile fact mapping (pure)
    features.py             # AggregateFeatures computation (pure)
    snapshot.py               # builds LLMSnapshot from facts + aggregates
    analyzer.py                # GitHubAnalyzer: public entrypoint, orchestrates
                                #   fetch -> normalize -> aggregate -> snapshot
  models/
    github.py         # Pydantic models: GitHubProfile, Repository,
                       #   AggregateFeatures, LLMSnapshot, Limitations,
                       #   GitHubAnalysisResult (top-level container)
  core/
    auth.py            # + load_github_token_from_env() reading GITHUB_TOKEN
    utils.py           # reused as-is: retry_async decorator
```

Key decisions:
- `GitHubAnalyzer` does **not** subclass `BaseScraper` — ingestion is pure async HTTP with no Playwright `page`. It optionally accepts the existing `ProgressCallback` (`on_start`/`on_progress`/`on_complete`/`on_error`) for parity with the other scrapers.
- `GitHubClient` uses `httpx.AsyncClient` (new dependency; `requests` in the existing stack is sync-only) wrapped with the existing `@retry_async` decorator from `core/utils.py`.
- All normalizer/feature/hygiene functions are pure (no I/O) — independently unit-testable.
- Token loading mirrors the existing `load_credentials_from_env()` pattern: `load_github_token_from_env()` reads `GITHUB_TOKEN` from `.env`.
- Entry point: `GitHubAnalyzer(token=...).analyze(github_url) -> GitHubAnalysisResult`.

## 11. Final Recommended JSON Schema

```jsonc
{
  "source_metadata": {
    "input_url_raw": "https://github.com/janedoe/",
    "resolved_username": "janedoe",
    "account_type": "USER",
    "fetched_at": "2026-07-04T18:22:31Z",
    "api_layers_used": ["graphql", "rest"],
    "authenticated": true
  },
  "parser_metadata": {
    "analyzer_version": "1.0.0",
    "graphql_query_cost": 12,
    "rate_limit_remaining_after": 4988,
    "repos_fetched": 47,
    "repos_hygiene_checked": 40,
    "repos_capped": false
  },
  "profile": {
    "login": "janedoe",
    "name": "Jane Doe",
    "bio": "Backend engineer, distributed systems",
    "company": "@some-startup",
    "location": "Toronto, ON",
    "website_url": "https://janedoe.dev",
    "email": null,
    "twitter_username": null,
    "followers_count": 132,
    "following_count": 45,
    "public_repos_count": 47,
    "public_gists_count": 3,
    "account_created_at": "2016-02-11T00:00:00Z",
    "avatar_url": "https://avatars.githubusercontent.com/u/123456",
    "is_hireable": true,
    "organizations": ["some-startup", "oss-collective"],
    "public_contribution_calendar_total": 812
  },
  "repositories": [
    {
      "id": "R_kgDOJx1abc",
      "name": "distributed-queue",
      "full_name": "janedoe/distributed-queue",
      "description": "A lightweight distributed task queue in Go",
      "url": "https://github.com/janedoe/distributed-queue",
      "homepage_url": null,
      "owner_login": "janedoe",
      "owner_type": "USER",
      "is_fork": false,
      "is_archived": false,
      "is_template": false,
      "is_mirror": false,
      "visibility": "PUBLIC",
      "default_branch": "main",
      "primary_language": "Go",
      "languages": {"Go": 88210, "Dockerfile": 1204, "Makefile": 512},
      "topics": ["distributed-systems", "go", "queue"],
      "license_spdx_id": "MIT",
      "stars": 214,
      "forks": 18,
      "watchers": 214,
      "open_issues": 6,
      "size_kb": 3120,
      "created_at": "2022-03-01T00:00:00Z",
      "updated_at": "2026-06-30T00:00:00Z",
      "pushed_at": "2026-06-28T00:00:00Z",
      "releases_count": 9,
      "latest_release_tag": "v1.4.0",
      "latest_release_at": "2026-05-10T00:00:00Z",
      "has_issues": true,
      "has_projects": false,
      "has_wiki": false,
      "has_pages": false,
      "has_discussions": false,
      "readme_present": true,
      "readme_length_chars": 4820,
      "has_ci": true,
      "has_tests": true,
      "has_docker": true,
      "has_lint_config": true,
      "has_package_manifest": true,
      "contributors_count": 4,
      "repo_age_days": 1585,
      "days_since_last_push": 6,
      "commit_activity_proxy": "ACTIVE_30D",
      "repo_type_guess": "ORIGINAL",
      "is_likely_portfolio_demo": false,
      "hygiene_signals_checked": true
    },
    {
      "id": "R_kgDOJx1xyz",
      "name": "react",
      "full_name": "janedoe/react",
      "description": "A declarative, efficient, and flexible JavaScript library",
      "url": "https://github.com/janedoe/react",
      "homepage_url": "https://reactjs.org",
      "owner_login": "janedoe",
      "owner_type": "USER",
      "is_fork": true,
      "is_archived": false,
      "is_template": false,
      "is_mirror": false,
      "visibility": "PUBLIC",
      "default_branch": "main",
      "primary_language": "JavaScript",
      "languages": {"JavaScript": 512000},
      "topics": [],
      "license_spdx_id": "MIT",
      "stars": 0,
      "forks": 0,
      "watchers": 0,
      "open_issues": 0,
      "size_kb": 210000,
      "created_at": "2021-01-15T00:00:00Z",
      "updated_at": "2021-01-15T00:00:00Z",
      "pushed_at": "2021-01-15T00:00:00Z",
      "releases_count": 0,
      "latest_release_tag": null,
      "latest_release_at": null,
      "has_issues": false,
      "has_projects": false,
      "has_wiki": false,
      "has_pages": false,
      "has_discussions": false,
      "readme_present": true,
      "readme_length_chars": null,
      "has_ci": null,
      "has_tests": null,
      "has_docker": null,
      "has_lint_config": null,
      "has_package_manifest": null,
      "contributors_count": null,
      "repo_age_days": 1885,
      "days_since_last_push": 2006,
      "commit_activity_proxy": "STALE",
      "repo_type_guess": "FORK",
      "is_likely_portfolio_demo": false,
      "hygiene_signals_checked": false
    }
  ],
  "aggregate_features": {
    "total_repos_fetched": 47,
    "original_repos_count": 31,
    "forked_repos_count": 14,
    "archived_repos_count": 3,
    "template_repos_count": 1,
    "active_repos_30d": 6,
    "active_repos_90d": 11,
    "active_repos_365d": 19,
    "stale_repos_count": 9,
    "total_stars": 640,
    "total_forks_received": 82,
    "median_stars_per_original_repo": 4.0,
    "top_languages": [
      {"language": "Go", "repo_count": 14, "total_bytes": 981200},
      {"language": "Python", "repo_count": 9, "total_bytes": 402100},
      {"language": "TypeScript", "repo_count": 5, "total_bytes": 220500}
    ],
    "top_topics": [
      {"topic": "distributed-systems", "count": 6},
      {"topic": "go", "count": 5}
    ],
    "repo_age_distribution": {"min_days": 40, "max_days": 3200, "median_days": 890},
    "account_age_days": 3800,
    "maintenance_consistency_score_raw": 0.61,
    "documentation_coverage_ratio": 0.74,
    "testing_coverage_ratio": 0.42,
    "ci_coverage_ratio": 0.35,
    "collaboration_repo_count": 8,
    "breadth_language_count": 6,
    "releases_shipped_total": 22,
    "top_evidence_repos": ["R_kgDOJx1abc", "R_kgDOJx1def", "R_kgDOJx1ghi"],
    "forks_excluded_count": 14,
    "archived_excluded_count": 3,
    "templates_excluded_count": 1
  },
  "llm_snapshot": {
    "login": "janedoe",
    "account_age_years": 10.4,
    "public_repos": 47,
    "original_repos": 31,
    "followers": 132,
    "top_languages": ["Go", "Python", "TypeScript"],
    "active_repos_90d": 11,
    "documentation_coverage_ratio": 0.74,
    "testing_coverage_ratio": 0.42,
    "ci_coverage_ratio": 0.35,
    "collaboration_repo_count": 8,
    "top_evidence_repos": [
      {
        "name": "distributed-queue",
        "description": "A lightweight distributed task queue in Go",
        "stars": 214,
        "language": "Go",
        "last_pushed": "2026-06-28",
        "has_tests": true,
        "has_ci": true,
        "readme_present": true,
        "repo_type": "ORIGINAL"
      }
    ],
    "notable_gaps": []
  },
  "limitations": {
    "profile_not_found": false,
    "partial_fetch": false,
    "repos_truncated": false,
    "rate_limited": false,
    "hygiene_signals_checked_ratio": 0.85,
    "no_public_activity": false,
    "contribution_calendar_may_undercount_private_activity": true,
    "reason": null,
    "notes": [
      "Contribution calendar reflects only activity visible to an unauthenticated GitHub viewer; private-repo contributions are excluded by GitHub itself, not by this pipeline.",
      "Contributors count capped at first 5 returned by GitHub contributors API; not exhaustive for large repos, and null when the endpoint errors (e.g. 403 on oversized repos)."
    ]
  }
}
```

## 12. Design Tradeoffs and Limitations

- **Why not pure REST:** N+1 round trips (900+ calls for 300 repos) vs. GraphQL's 1–3. Tradeoff: GraphQL can't expose file contents, so hygiene checks still need REST.
- **Why cap hygiene REST checks to a relevant subset:** a candidate with 300 repos (many stale class assignments) would burn the entire rate-limit budget on repos unlikely to be evidence. The `hygiene_signals_checked` flag makes the skip auditable rather than silently incomplete.
- **`repo_type_guess` and `is_likely_portfolio_demo` are explicitly heuristic** (`_guess`, `is_likely_` naming) — pattern matches, not verified facts. Prevents downstream stages from treating them as ground truth.
- **`maintenance_consistency_score_raw` carries a `_raw` suffix** deliberately, to avoid implying it's an evaluative score — it's a plain ratio.
- **README/file contents excluded from the LLM snapshot** for token-budget reasons — only presence/length flags are surfaced; full text stays in the raw payload for on-demand deep dives.
- **Star/fork "who" lists excluded entirely**, not just from the snapshot — no identified evaluation use case, meaningful storage/privacy cost for no benefit.
- **Raw payloads stored separately from normalized data** so normalization logic can be re-run later without re-hitting the API and burning rate limit, and so a given `has_ci` or `repo_type_guess` decision is auditable.
- **`GitHubAnalyzer` doesn't subclass `BaseScraper`** — that base class is Playwright-page-centric; this pipeline is pure async HTTP.
- **GraphQL requires authentication** — this is a hard API constraint, not a design choice. Without `GITHUB_TOKEN`, the analyzer transparently falls back to unauthenticated REST at 60 req/hr with reduced fidelity (`limitations.reason = "unauthenticated_rate_limit"`), rather than failing outright.
- **Per-signal REST fault tolerance is required, not optional** — large/popular repos (e.g. Linux-kernel-scale) return `403` on the `/contributors` endpoint ("history or contributor list is too large"). Each hygiene REST call is fetched and caught independently so one repo's edge case doesn't abort the whole candidate's analysis.
