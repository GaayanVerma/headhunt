# GitHub AI-Assisted Analysis Layer — Design Documentation

Sibling document to `github-analyzer-design.md`. This layer is implemented: see
`linkedin_scraper/models/ai_insights.py`, `linkedin_scraper/models/contributions.py`,
`linkedin_scraper/github/ai_analyzer.py`, `linkedin_scraper/github/repo_analyzer.py`,
`linkedin_scraper/github/contributions.py`, and `linkedin_scraper/llm/`.

This plan extends, and does not modify the behavior of, the existing non-judgmental pipeline described in
`github-analyzer-design.md` (`GitHubClient`, `GitHubProfileFetcher`, `hygiene.py`, `normalizer.py`, `features.py`,
`snapshot.py`, `GitHubAnalyzer.analyze()`, `GitHubAnalysisResult`). Nothing in the existing four-layer model is
renamed or restructured; this adds three more layers on top, plus one file-content-driven insight layer.

---

## 1. Architecture Update

### 1.1 New orchestrator, not a modified entrypoint

Add a new class `GitHubAIAnalyzer` in `linkedin_scraper/github/ai_analyzer.py` that **composes** the existing
`GitHubAnalyzer` rather than modifying it:

```python
class GitHubAIAnalyzer:
    def __init__(
        self,
        github_token: Optional[str] = None,
        llm_client: Optional["LLMClient"] = None,
        callback: Optional[ProgressCallback] = None,
        include_repo_insights: bool = True,
        include_contributions: bool = True,
        max_repos_for_llm_insights: int = 5,
    ):
        ...

    async def analyze(self, github_url: str) -> "CandidateGitHubAIResult":
        base_result = await GitHubAnalyzer(token=self.github_token, callback=self.callback).analyze(github_url)
        # short-circuit on profile_not_found exactly like the base analyzer
        contribution_facts = await self._fetch_contributions(...)   # if include_contributions
        derived_contribution_metrics = compute_contribution_metrics(contribution_facts)
        llm_repo_insights = await self._generate_repo_insights(base_result)  # if include_repo_insights
        candidate_llm_snapshot = build_candidate_llm_snapshot(base_result, llm_repo_insights, derived_contribution_metrics)
        return CandidateGitHubAIResult(
            github_facts=base_result,          # reuse, not re-derive
            contribution_facts=contribution_facts,
            derived_contribution_metrics=derived_contribution_metrics,
            llm_repo_insights=llm_repo_insights,
            candidate_llm_snapshot=candidate_llm_snapshot,
        )
```

Rationale for a **separate orchestrator** over an `include_ai_insights=True` flag on `GitHubAnalyzer.analyze()`:
- `GitHubAnalyzer` is deliberately non-judgmental, deterministic, and has no LLM/network-to-Anthropic dependency
  today. Keeping it that way means it stays cheap, fast, and testable without any API key, and any caller who
  only wants `github-analyzer-design.md`'s existing behavior is completely unaffected (no new required env vars,
  no new failure modes, no new latency).
- AI insight generation is a materially different reliability/cost/latency profile (LLM calls, retries on
  malformed JSON, per-repo file fetch). It deserves its own progress callback phases, its own opt-in flags, and
  its own error containment so an LLM outage never fails the deterministic pipeline.
- Mirrors an existing pattern already visible in this codebase: `samples/scrape_person.py` composes independent
  stages (`ResumeParser`, `PersonScraper`, `GitHubAnalyzer`) rather than baking everything into one class.

`GitHubAIAnalyzer.analyze()` still degrades gracefully: if the LLM stage or contributions stage throws, catch it,
set an entry in `candidate_llm_snapshot.limitations`/a new `ai_limitations` block, and still return the
deterministic `github_facts` (never let an LLM/API failure blank out data that was already successfully fetched).

### 1.2 Persistence

Extend the per-candidate payload write step (today informal, would be added at the CLI/sample-script layer) to
write a second file alongside `github_profile_payload.json`:

- `linkedin_scraper/candidates/<Name>/github_profile_payload.json` — unchanged, still `GitHubAnalysisResult.to_json()`.
- `linkedin_scraper/candidates/<Name>/github_ai_insights_payload.json` — new, `CandidateGitHubAIResult.to_json()`.

Keeping these as two files (rather than merging) preserves the existing design doc's persisted-artifact contract
and lets a caller who only wants the deterministic pipeline avoid ever paying for/depending on the AI file.

### 1.3 Where new modules attach

```
linkedin_scraper/
  models/
    github.py                 # UNCHANGED (existing 4-layer models)
    ai_insights.py             # NEW: llm_repo_insights layer models + CandidateGitHubAIResult container
    contributions.py           # NEW: contribution_facts + derived_contribution_metrics models
  github/
    client.py                  # UNCHANGED (reused as-is)
    queries.py                 # EDIT: add CONTRIBUTIONS_QUERY, add repo tree/blob helpers stay in REST not GraphQL
    fetcher.py                 # UNCHANGED
    hygiene.py                 # UNCHANGED (reused directly by repo_analyzer.py for pre-filtering)
    normalizer.py               # UNCHANGED
    features.py                 # UNCHANGED
    snapshot.py                  # EDIT (additive): add build_candidate_llm_snapshot() — new function, not a change to build_llm_snapshot()
    analyzer.py                  # UNCHANGED
    ai_analyzer.py               # NEW: GitHubAIAnalyzer orchestrator
    repo_analyzer.py             # NEW: file selection + tree fetch + content fetch + monorepo detection
    contributions.py             # NEW: contribution GraphQL fetch + normalize + derive
  llm/
    __init__.py                 # NEW
    base.py                      # NEW: LLMClient ABC/Protocol, LLMResponse, LLMError types
    anthropic_client.py          # NEW: AnthropicLLMClient(LLMClient)
    prompts.py                   # NEW: prompt template constants + rendering functions
    json_parsing.py              # NEW: strict-JSON extraction + retry-on-malformed-JSON helper
    cache.py                     # NEW: content-hash based insight cache (in-memory + optional on-disk JSON store)
  core/
    auth.py                      # EDIT (additive): add load_anthropic_key_from_env()
    exceptions.py                # EDIT (additive): add LLMError, LLMResponseParsingError
```

No existing file's public function signatures change. `queries.py` gains a new query string constant; nothing is
removed. `snapshot.py` gains a new function; `build_llm_snapshot()` is untouched so `GitHubAnalyzer` keeps working
byte-for-byte as before.

---

## 2. Full Extended Schema

### 2.1 `linkedin_scraper/models/ai_insights.py` (NEW FILE)

```python
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# ---- Bands (bounded discrete scale, never a single scalar score) ----
# LOW / MEDIUM / HIGH / UNKNOWN — UNKNOWN is explicit, not omission.
Band = str  # Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] enforced via validator or Enum


class EvidenceFileRef(BaseModel):
    repo_full_name: str
    path: str
    reason: str  # why this file was cited, e.g. "defines primary CLI entrypoint"


class CodeQualitySignals(BaseModel):
    """Structured, banded — NOT a single quality score."""
    readability: Band = "UNKNOWN"
    modularity: Band = "UNKNOWN"
    project_structure_clarity: Band = "UNKNOWN"
    dependency_hygiene: Band = "UNKNOWN"
    testing_presence: Band = "UNKNOWN"
    documentation_quality: Band = "UNKNOWN"
    ci_cd_presence: Band = "UNKNOWN"
    deployability: Band = "UNKNOWN"
    maintainability_risk_flags: List[str] = []   # e.g. "no_dependency_pinning", "single_giant_file"
    confidence: Band = "UNKNOWN"                  # model's own confidence in the above bands
    evidence: List[EvidenceFileRef] = []


class RepoInsight(BaseModel):
    """One LLM-generated insight block for a single repository."""
    repo_id: str                   # matches Repository.id from github_facts, joins the two layers
    repo_full_name: str
    repo_summary: str
    workflow_summary: Optional[str] = None
    architecture_summary: Optional[str] = None
    libraries_frameworks_used: List[str] = []
    code_quality: CodeQualitySignals = CodeQualitySignals()
    engineering_hygiene_notes: List[str] = []
    repo_maturity_guess: str = "UNKNOWN"   # PROTOTYPE/ACTIVE_PROJECT/MATURE/ARCHIVED_OR_ABANDONED/UNKNOWN
    risk_flags: List[str] = []
    confidence: Band = "UNKNOWN"
    evidence_files: List[EvidenceFileRef] = []
    files_analyzed_count: int = 0
    files_truncated: bool = False         # true if repo/monorepo was larger than sampling budget
    is_monorepo_guess: bool = False
    llm_model_used: Optional[str] = None
    generated_at: Optional[datetime] = None
    generation_error: Optional[str] = None   # non-null => insight is partial/degraded, never silently dropped


class LLMRepoInsightsLimitations(BaseModel):
    repos_analyzed_count: int = 0
    repos_skipped_count: int = 0
    repos_skipped_reason: Optional[str] = None   # e.g. "capped_at_max_repos_for_llm_insights"
    malformed_json_retry_count: int = 0
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    notes: List[str] = []


class LLMRepoInsights(BaseModel):
    """Layer 3 (new): llm_repo_insights."""
    insights: List[RepoInsight] = []
    limitations: LLMRepoInsightsLimitations = LLMRepoInsightsLimitations()


class CandidateLLMSnapshot(BaseModel):
    """Layer 6 (new): compact combined snapshot for a downstream/final consuming stage.
    Still non-judgmental - no verdict, no hire/no-hire, no single score."""
    login: str
    github_facts_snapshot: dict          # existing LLMSnapshot.model_dump(), embedded as-is
    top_repo_insights: List[RepoInsight] = []   # capped subset, highest-evidence repos only
    contribution_summary: Optional[dict] = None  # DerivedContributionMetrics.model_dump()
    combined_notable_gaps: List[str] = []
    combined_limitations_notes: List[str] = []
    generated_at: Optional[datetime] = None


class CandidateGitHubAIResult(BaseModel):
    """Top-level container persisted as github_ai_insights_payload.json."""
    github_facts: "GitHubAnalysisResult"          # reused as-is from models.github (layer 1+2 container)
    llm_repo_insights: LLMRepoInsights = LLMRepoInsights()
    contribution_facts: "ContributionFacts"        # from models.contributions
    derived_contribution_metrics: "DerivedContributionMetrics"
    candidate_llm_snapshot: CandidateLLMSnapshot

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)
```

Note: `github_facts` layer and `deterministic_repo_signals` layer map directly onto the EXISTING
`GitHubAnalysisResult.profile`/`.repositories` (raw+normalized facts) and `.aggregate_features`/per-`Repository`
hygiene fields (`has_ci`, `has_tests`, etc.) respectively — no duplication, just reuse by reference. The only
addition needed to `deterministic_repo_signals` is exposed through `repo_analyzer.py`'s tree-fetch output feeding
`RepoInsight.files_analyzed_count` / `is_monorepo_guess`, which are LLM-layer bookkeeping fields, not new
deterministic Repository fields — **no edits to `models/github.py` are required**.

### 2.2 `linkedin_scraper/models/contributions.py` (NEW FILE)

```python
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel


class ContributedRepository(BaseModel):
    repo_full_name: str
    owner_login: str
    is_own_repo: bool               # owner_login == candidate login
    is_org_repo: bool               # owned by an org the candidate belongs to (from profile.organizations)
    is_external_repo: bool          # neither own nor org - true external OSS participation
    commit_contributions: int = 0
    pull_request_contributions: int = 0
    pull_request_review_contributions: int = 0
    issue_contributions: int = 0
    first_contribution_at: Optional[datetime] = None   # best-effort, from earliest sampled page
    last_contribution_at: Optional[datetime] = None


class ContributionFacts(BaseModel):
    """Layer 4 (new): raw/normalized GitHub contribution API data."""
    login: str
    contribution_period_from: Optional[datetime] = None
    contribution_period_to: Optional[datetime] = None
    total_commit_contributions: int = 0
    total_pull_request_contributions: int = 0
    total_pull_request_review_contributions: int = 0
    total_issue_contributions: int = 0
    total_repository_contributions: int = 0   # new-repo-creation contributions, from GraphQL
    contributed_repositories: List[ContributedRepository] = []
    external_open_source_repositories: List[str] = []   # subset of contributed_repositories, full_names only
    limitations: "ContributionLimitations"


class ContributionLimitations(BaseModel):
    graphql_window_limited_to_one_year: bool = True
    contributions_collection_requires_auth: bool = True
    private_contributions_excluded: bool = True
    partial_fetch: bool = False
    rate_limited: bool = False
    by_repository_pagination_truncated: bool = False
    reason: Optional[str] = None
    notes: List[str] = []


class DerivedContributionMetrics(BaseModel):
    """Layer 5 (new): computed ratios/trends over contribution_facts. Non-judgmental."""
    total_contributed_repos_count: int = 0
    own_repos_count: int = 0
    org_repos_count: int = 0
    external_repos_count: int = 0
    external_repo_ratio: float = 0.0             # external / total contributed repos
    external_contribution_share: float = 0.0     # (commits+PRs+reviews+issues to external) / total of same
    review_to_pr_ratio: Optional[float] = None    # reviews / PRs opened, signals reviewing-others'-code behavior
    contribution_consistency: str = "UNKNOWN"     # SPARSE/OCCASIONAL/REGULAR/UNKNOWN - based on months-with-activity within window
    contribution_recency: str = "UNKNOWN"           # ACTIVE_30D/90D/365D/STALE/UNKNOWN - reuses same bucket vocabulary as Repository.commit_activity_proxy for consistency
    ecosystem_breadth_count: int = 0              # distinct primary languages across external_open_source_repositories
    notable_gaps: List[str] = []                   # e.g. "no_external_oss_contributions_detected"
```

`ContributionFacts.limitations` forward-refs `ContributionLimitations`; call `model_rebuild()` at module bottom,
matching Pydantic v2 forward-ref conventions already implicit in `models/github.py`'s ordering (models defined
top-down with no forward refs there, so this module should just define `ContributionLimitations` before
`ContributionFacts` to avoid needing forward-ref rebuild at all — simpler, follow that ordering).

---

## 3. Repository AI Insight Prompt (full text)

File: `linkedin_scraper/llm/prompts.py`, constant `REPO_INSIGHT_SYSTEM_PROMPT` + `render_repo_insight_user_prompt(...)`.

**System prompt:**

```
You are a code-analysis assistant that produces STRICTLY FACTUAL, EVIDENCE-BACKED structural
observations about a single GitHub repository, for use in a non-judgmental candidate data
pipeline. You are NOT a hiring evaluator.

Hard rules, no exceptions:
1. You will be given a repository's manifest files, README, CI config, and a sampled subset of
   source/test files (not the whole repo). Base every claim ONLY on the files you were given.
   Never invent file contents, libraries, or behavior you cannot see evidence for.
2. For EVERY factual claim you make (in repo_summary, workflow_summary, architecture_summary,
   libraries_frameworks_used, code_quality subfields, engineering_hygiene_notes, risk_flags),
   you MUST cite at least one evidence_files entry (repo_full_name + path + a short reason)
   that supports it. Claims without a citable file should be omitted or explicitly marked low confidence.
3. Output ONLY valid JSON matching the exact schema given below. No prose outside the JSON. No
   markdown code fences. No trailing commentary.
4. Every banded field (readability, modularity, project_structure_clarity, dependency_hygiene,
   testing_presence, documentation_quality, ci_cd_presence, deployability, confidence) MUST be
   exactly one of: "LOW", "MEDIUM", "HIGH", "UNKNOWN". Use "UNKNOWN" whenever the sampled files
   do not give you enough evidence - do not guess a band just to fill the field.
5. NEVER output a hiring verdict, quality score, ranking, "hire"/"no hire", "strong"/"weak"
   candidate language, or any single overall score. This output is one non-judgmental input
   layer among several that a separate, later stage may use - it must not editorialize.
6. If the repository appears to be a tutorial follow-along, a forked/template instance, or a
   toy/demo project rather than original production-oriented work, say so factually in
   repo_summary and reflect it in repo_maturity_guess - but do not use judgmental language.
7. If you were given only a subset of a large or monorepo-structured project, say so explicitly
   (this will already be reflected by the caller in files_truncated/is_monorepo_guess - you do not
   need to set those fields yourself, just avoid overstating confidence given a partial view).

Output schema (produce exactly these keys, matching types):
{
  "repo_summary": "string",
  "workflow_summary": "string or null",
  "architecture_summary": "string or null",
  "libraries_frameworks_used": ["string", ...],
  "code_quality": {
    "readability": "LOW|MEDIUM|HIGH|UNKNOWN",
    "modularity": "LOW|MEDIUM|HIGH|UNKNOWN",
    "project_structure_clarity": "LOW|MEDIUM|HIGH|UNKNOWN",
    "dependency_hygiene": "LOW|MEDIUM|HIGH|UNKNOWN",
    "testing_presence": "LOW|MEDIUM|HIGH|UNKNOWN",
    "documentation_quality": "LOW|MEDIUM|HIGH|UNKNOWN",
    "ci_cd_presence": "LOW|MEDIUM|HIGH|UNKNOWN",
    "deployability": "LOW|MEDIUM|HIGH|UNKNOWN",
    "maintainability_risk_flags": ["string", ...],
    "confidence": "LOW|MEDIUM|HIGH|UNKNOWN",
    "evidence": [{"path": "string", "reason": "string"}, ...]
  },
  "engineering_hygiene_notes": ["string", ...],
  "repo_maturity_guess": "PROTOTYPE|ACTIVE_PROJECT|MATURE|ARCHIVED_OR_ABANDONED|UNKNOWN",
  "risk_flags": ["string", ...],
  "confidence": "LOW|MEDIUM|HIGH|UNKNOWN",
  "evidence_files": [{"path": "string", "reason": "string"}, ...]
}
```

**User prompt template** (rendered per repo by `render_repo_insight_user_prompt`):

```
Repository: {repo_full_name}
Description (from GitHub metadata): {description_or_"none provided"}
Primary language: {primary_language}
Deterministic signals already computed (do not re-derive, use as context only):
  has_ci={has_ci}, has_tests={has_tests}, has_docker={has_docker},
  has_lint_config={has_lint_config}, has_package_manifest={has_package_manifest},
  repo_type_guess={repo_type_guess}, is_likely_portfolio_demo={is_likely_portfolio_demo}
Monorepo detected: {is_monorepo_guess} (subprojects: {subproject_paths_or_none})
Files sampled below ({files_analyzed_count} of an estimated {total_file_count_in_tree} total,
truncated={files_truncated}):

--- FILE: {path_1} ({size_bytes} bytes) ---
{content_1_truncated_to_budget}

--- FILE: {path_2} ({size_bytes} bytes) ---
{content_2_truncated_to_budget}

... (repeat for each sampled file, in the order: manifests, README, CI config, Dockerfile,
     entrypoints, then representative source/test sample)

Produce your analysis of ONLY this repository as a single JSON object matching the schema in
the system prompt. Cite evidence_files using the exact paths shown above.
```

Per-file content is truncated to a configurable budget (default 4000 chars/file, keeps head prioritized since
imports/definitions/docstrings cluster there) and the whole prompt is capped at a total token budget (default
~12k input tokens per repo, configurable) - if the sampled set would exceed budget, `repo_analyzer.py` drops
lowest-priority files first (see file-selection priority order in Section 6.2), not the prompt-builder silently
truncating mid-file-list.

---

## 4. Contribution Analysis Schema + GraphQL Query Additions

Full new query, added to `linkedin_scraper/github/queries.py` as `CONTRIBUTIONS_QUERY`:

```graphql
query CandidateContributions($login: String!, $from: DateTime!, $to: DateTime!, $repoCursor: String) {
  rateLimit { remaining resetAt cost }
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      totalRepositoryContributions
      startedAt
      endedAt
      commitContributionsByRepository(maxRepositories: 100) {
        repository {
          nameWithOwner
          owner { login }
          isFork
          primaryLanguage { name }
        }
        contributions { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: 100) {
        repository {
          nameWithOwner
          owner { login }
          isFork
          primaryLanguage { name }
        }
        contributions(first: 1, orderBy: {direction: DESC}) {
          totalCount
          nodes { pullRequest { createdAt } }
        }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner owner { login } }
        contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner owner { login } }
        contributions { totalCount }
      }
    }
  }
}
```

Notes on this query, to document explicitly in the design doc:
- `contributionsCollection(from:, to:)` **only accepts a window up to 1 year** per GitHub's API constraints - if
  `to - from > 1 year` GitHub silently clamps it. To approximate multi-year history, the fetcher issues this
  query **N times** with sequential 1-year windows (e.g. last 3 years = 3 calls with rolling `from`/`to`), then
  the normalizer sums/merges results into one `ContributionFacts`. This is a deliberate, disclosed
  multi-call strategy - document it plainly as a rate-limit/cost tradeoff (each call costs GraphQL points).
  Default: fetch 2 windows (current + prior year) unless a `contribution_years` param requests more.
- `*ByRepository(maxRepositories: 100)` is NOT cursor-paginated by GitHub's schema (it's a flat capped list, no
  `pageInfo`) - so "pagination" here means capping at 100 repos per category per window and flagging
  `by_repository_pagination_truncated=True` if a candidate contributes to more than 100 repos in one window
  (rare, but must be disclosed, not silently dropped).
- No REST equivalent exists for `contributionsCollection` - this is GraphQL-only, matching the existing design
  doc's stated rule ("Contribution calendar: GraphQL only").
- Requires the SAME `GITHUB_TOKEN` already loaded via `load_github_token_from_env()` - no new scope needed since
  contribution counts are visible for any public activity of a public profile; if unauthenticated
  (`client.authenticated is False`), skip the contributions stage entirely and set
  `ContributionLimitations.contributions_collection_requires_auth=True` +
  `partial_fetch=True` + a note, mirroring how `fetcher.py` already special-cases unauthenticated GraphQL.

### 4.1 Normalization -> derivation flow (`linkedin_scraper/github/contributions.py`)

```python
class ContributionFetcher:
    def __init__(self, client: GitHubClient): ...
    async def fetch(self, username: str, years: int = 2) -> Dict[str, Any]: ...
        # loops `years` 1-year windows ending at "now", calling CONTRIBUTIONS_QUERY per window,
        # merges via _merge_windows(), returns raw dict bundle (mirrors fetcher.py's raw-bundle pattern)

def normalize_contributions(raw: Dict[str, Any], profile_login: str, profile_orgs: List[str]) -> ContributionFacts: ...
    # classifies each *ByRepository entry: is_own_repo (owner==login), is_org_repo (owner in profile_orgs),
    # is_external_repo (neither) - joins commit/PR/review/issue counts per repo_full_name into ContributedRepository

def compute_contribution_metrics(facts: ContributionFacts) -> DerivedContributionMetrics: ...
    # pure function, same discipline as features.compute_aggregate_features(): ratios, breadth counts,
    # consistency/recency buckets from first/last_contribution_at, notable_gaps list
```

`ContributionFetcher.fetch` reuses `client.graphql()` and thus `retry_async` + rate-limit handling from
`client.py` automatically - no new retry logic needed.

---

## 5. Code Quality Model (structured fields, bands, evidence discipline)

Already fully specified as `CodeQualitySignals` in Section 2.1. Design principles to carry into the doc:

- **Never a scalar.** Eight independent banded dimensions (`readability`, `modularity`,
  `project_structure_clarity`, `dependency_hygiene`, `testing_presence`, `documentation_quality`,
  `ci_cd_presence`, `deployability`) plus a separate `maintainability_risk_flags` list and its own `confidence`
  band — deliberately mirrors the existing codebase's refusal to produce a single quality score anywhere in
  `AggregateFeatures`/`LLMSnapshot`.
- **Bands, not free-text or 1-10 scales.** `LOW/MEDIUM/HIGH/UNKNOWN` is a 4-value enum, easy to validate
  post-hoc against the JSON schema, easy to aggregate/filter downstream, and forces the LLM to commit to
  `UNKNOWN` rather than fabricate a plausible-sounding score when evidence is thin.
- **`_guess`/`_raw` naming discipline carried forward:** `repo_maturity_guess` (LLM-derived, explicitly a guess,
  same naming convention as `repo_type_guess` in `models/github.py`), `is_monorepo_guess` (bookkeeping, computed
  deterministically by `repo_analyzer.py`, not the LLM — still named `_guess` because monorepo detection via
  "multiple manifest files at different depths" is itself a heuristic).
- **Evidence is mandatory, not optional decoration.** `CodeQualitySignals.evidence` and `RepoInsight.evidence_files`
  are both `List[EvidenceFileRef]` with a `reason` string — enforced structurally by the prompt (Section 3, rule
  2) and validated at parse time: `json_parsing.py`'s validator rejects (triggers one retry) any repo-quality
  response where a non-UNKNOWN band has zero evidence entries.
- **Confidence is explicit and separate from the bands themselves** — a `HIGH` readability band with `LOW`
  confidence is a valid, meaningful combination (e.g. LLM saw only 3 files but they looked clean); collapsing
  these into one field would lose that distinction.

---

## 6. GitHub API Usage Strategy

### 6.1 GraphQL additions
- New `CONTRIBUTIONS_QUERY` (Section 4) — separate query, separate fetch cycle from `PROFILE_AND_REPOS_QUERY`, run
  only when `include_contributions=True`. Reuses `GitHubClient.graphql()` unchanged.
- No changes needed to `PROFILE_AND_REPOS_QUERY` itself — `organizations(first: 20)` already fetched there gives
  `profile_orgs` for contribution classification (own/org/external) without an extra call.

### 6.2 REST additions (new module `linkedin_scraper/github/repo_analyzer.py`)

Two new REST call types, both via `client.rest_get()` (already handles rate limiting/retry/backoff):

1. **Tree fetch**: `GET /repos/{owner}/{repo}/git/trees/{branch_or_sha}?recursive=1` — one call per repo selected
   for LLM insight generation (capped at `max_repos_for_llm_insights`, default 5, chosen via the SAME
   `top_evidence_repos` ranking already computed by `features._rank_evidence_repos()` — reuse, don't reinvent).
   Returns full path list + blob sizes + `truncated: true/false` flag from GitHub itself (GitHub truncates trees
   over ~100k entries — that flag maps directly onto `RepoInsight.files_truncated`).
2. **Content fetch**: `GET /repos/{owner}/{repo}/contents/{path}` per selected file, base64-decoded
   (`base64.b64decode(resp["content"]).decode("utf-8", errors="replace")`), concurrency-capped via
   `asyncio.Semaphore` exactly like `fetcher._fetch_hygiene_signals` does (`REST_CONCURRENCY = 5` pattern reused).

**File selection algorithm** (`select_files_for_analysis(tree_entries) -> List[SelectedFile]`), priority order,
budget-capped (default 25 files / repo, configurable):
1. Manifests at any depth: `package.json`, `pyproject.toml`, `setup.py`, `go.mod`, `Cargo.toml`, `pom.xml`,
   `build.gradle`, `Gemfile`, `composer.json`, `requirements.txt` — reuse `hygiene._MANIFEST_NAMES` set, extend
   with `requirements.txt`/`Cargo.toml`(already present)/`Gemfile`(present) — add `requirements.txt` if missing.
2. **Monorepo detection**: if manifests are found at 2+ distinct directory depths/subpaths (e.g.
   `packages/api/package.json` and `packages/web/package.json`), set `is_monorepo_guess=True` and allocate the
   file budget proportionally per subproject (e.g. 25 files / N subprojects, minimum 5 each) rather than
   exhausting the budget on the first subproject found.
3. `README.md` / `README` at repo root (and per-subproject root if monorepo).
4. CI config: `.github/workflows/*.yml`, `.gitlab-ci.yml`, `.circleci/config.yml` — reuse `hygiene._CI_NAMES`.
5. `Dockerfile`, `docker-compose.yml`.
6. Entrypoints by convention: `main.py`, `app.py`, `index.js`, `index.ts`, `server.js`, `cmd/*/main.go`,
   `src/main.rs`, `Main.java` — matched by filename pattern, prioritizing repo-root and shallow depth.
7. Test files — sample, not all: pick at most 3, prefer smallest-by-size (cheaper, often clearer) matching
   `hygiene._TEST_DIR_NAMES` dirs or `*_test.*`/`*.test.*`/`*_spec.*` patterns.
8. Representative source sample: remaining budget filled by picking files across distinct top-level directories
   (breadth over depth — one file per distinct dir prefix first, then round 2 if budget remains), preferring
   mid-size files (very tiny files = low signal, very large files = truncation risk) — sort candidates by
   `abs(size_bytes - median_size)` ascending as a simple heuristic, skip binary/vendored paths
   (`node_modules/`, `vendor/`, `dist/`, `build/`, `.min.js`, images/fonts by extension).
9. Hard caps: skip any single file over 100KB (configurable) entirely rather than truncating mid-content into
   the prompt (truncating a huge minified file wastes budget with a non-representative content), and skip if
   total selected-file bytes would exceed the prompt token budget from Section 3.

### 6.3 Caching strategy (`linkedin_scraper/llm/cache.py`)

Two independent cache keys, since tree/content fetches and LLM insight generation have different invalidation
triggers:
- **Repo tree + file content cache**: keyed by `(owner, repo, commit_sha)` where `commit_sha` is the tip of
  `default_branch` (already available from `Repository.default_branch` + one extra lightweight
  `GET /repos/{owner}/{repo}/commits/{branch}?per_page=1` call, or reuse the tree fetch's root `sha` from the
  `trees` response itself — prefer the latter, saves a call). Cache backend: simple on-disk JSON under
  `linkedin_scraper/candidates/<Name>/.github_cache/<owner>_<repo>_<sha>.json` (mirrors the existing per-candidate
  directory convention) — avoids re-fetching tree+contents for a repo whose HEAD hasn't moved since last run.
- **LLM insight cache**: keyed by `sha256(content of all selected files concatenated + prompt template version
  string + model id)`. If a repo's selected-file content hash is unchanged since a prior run AND the prompt
  version/model are unchanged, skip the LLM call entirely and reuse the cached `RepoInsight`. This directly
  addresses cost/latency: repeat runs against a candidate whose repos haven't changed cost zero LLM tokens.
  Store under the same `.github_cache/` dir as `llm_insight_<hash>.json`.
- Both caches are opt-in via a constructor flag (`use_cache: bool = True`) and fail open (cache miss/error ->
  just re-fetch/re-generate, never hard-fail the pipeline on a cache read/write error).

### 6.4 Rate-limit handling
- Reuses `GitHubClient._check_and_raise` / `RateLimitError` / `retry_async` verbatim — no new rate-limit code
  needed for GitHub calls. `repo_analyzer.py` and `contributions.py` both catch `RateLimitError` per-repo/per-window
  exactly like `fetcher._fetch_repo_hygiene` does (degrade that one file/repo to `None`/skipped rather than
  aborting the whole AI stage), and roll up a count into `LLMRepoInsightsLimitations`/`ContributionLimitations`.
- Anthropic-side rate limits/errors are handled independently inside `AnthropicLLMClient` (Section 7.3) via the
  SDK's own retry knobs plus an app-level `retry_async`-style wrapper for 429/5xx, separate from GitHub's limiter.

---

## 7. Python Implementation Guidance

### 7.1 New files to create
| File | Purpose |
|---|---|
| `linkedin_scraper/models/ai_insights.py` | `RepoInsight`, `CodeQualitySignals`, `EvidenceFileRef`, `LLMRepoInsights`, `CandidateLLMSnapshot`, `CandidateGitHubAIResult` |
| `linkedin_scraper/models/contributions.py` | `ContributedRepository`, `ContributionFacts`, `ContributionLimitations`, `DerivedContributionMetrics` |
| `linkedin_scraper/github/repo_analyzer.py` | file selection + tree/content fetch + monorepo detection |
| `linkedin_scraper/github/contributions.py` | `ContributionFetcher`, `normalize_contributions`, `compute_contribution_metrics` |
| `linkedin_scraper/github/ai_analyzer.py` | `GitHubAIAnalyzer` orchestrator |
| `linkedin_scraper/llm/__init__.py` | export `LLMClient`, `AnthropicLLMClient` |
| `linkedin_scraper/llm/base.py` | `LLMClient` ABC, `LLMResponse`, `LLMError` |
| `linkedin_scraper/llm/anthropic_client.py` | `AnthropicLLMClient(LLMClient)` |
| `linkedin_scraper/llm/prompts.py` | system/user prompt templates for repo insight generation |
| `linkedin_scraper/llm/json_parsing.py` | strict JSON extraction, schema validation, malformed-JSON retry loop |
| `linkedin_scraper/llm/cache.py` | tree/content cache + insight cache (Section 6.3) |

### 7.2 Existing files to edit (additive only, no signature changes to existing functions)
| File | Edit |
|---|---|
| `linkedin_scraper/github/queries.py` | Add `CONTRIBUTIONS_QUERY` constant |
| `linkedin_scraper/github/snapshot.py` | Add `build_candidate_llm_snapshot(github_facts, llm_repo_insights, derived_contribution_metrics) -> CandidateLLMSnapshot` |
| `linkedin_scraper/core/auth.py` | Add `load_anthropic_key_from_env() -> Optional[str]` (mirrors `load_github_token_from_env`, reads `ANTHROPIC_API_KEY` via `load_dotenv()`) |
| `linkedin_scraper/core/exceptions.py` | Add `LLMError(LinkedInScraperException)`, `LLMResponseParsingError(LLMError)` |
| `.env.example` | Add `ANTHROPIC_API_KEY=...` block with the same style of explanatory comment as the existing `GITHUB_TOKEN` block |
| `setup.py` / `requirements.txt` | Add `anthropic>=0.40.0` to `basic_requirements` / `requirements.txt` |
| `linkedin_scraper/github/__init__.py` | Export `GitHubAIAnalyzer` alongside existing `GitHubAnalyzer` |

### 7.3 Key function/class signatures

```python
# linkedin_scraper/llm/base.py
class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

class LLMClient(ABC):
    @abstractmethod
    async def complete(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.0
    ) -> LLMResponse: ...

class LLMError(Exception): ...
class LLMRateLimitError(LLMError): ...
class LLMResponseParsingError(LLMError): ...


# linkedin_scraper/llm/anthropic_client.py
class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-5-20250929"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    @retry_async(max_attempts=3, backoff=2.0, exceptions=(anthropic.APIConnectionError, anthropic.RateLimitError))
    async def complete(self, system_prompt, user_prompt, max_tokens=4096, temperature=0.0) -> LLMResponse:
        resp = await self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
        )
        return LLMResponse(text=resp.content[0].text, model=resp.model,
                            input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)


# linkedin_scraper/llm/json_parsing.py
async def complete_with_json_retry(
    llm: LLMClient, system_prompt: str, user_prompt: str, schema_validator: Callable[[dict], None],
    max_retries: int = 2,
) -> dict:
    """Calls llm.complete(), strips markdown fences if present, json.loads(), runs
    schema_validator(parsed) (raises ValueError on missing/invalid fields e.g. band not in
    {LOW,MEDIUM,HIGH,UNKNOWN} or non-UNKNOWN band with empty evidence). On JSONDecodeError or
    ValueError, appends a corrective follow-up instruction to user_prompt ('Your previous
    response was not valid JSON matching the schema: {error}. Return ONLY corrected JSON.')
    and retries up to max_retries times. Raises LLMResponseParsingError if still invalid."""


# linkedin_scraper/github/repo_analyzer.py
@dataclass
class SelectedFile:
    path: str
    size_bytes: int
    category: str   # "manifest"|"readme"|"ci"|"docker"|"entrypoint"|"test"|"sample"

async def fetch_repo_tree(client: GitHubClient, owner: str, repo: str, branch: str) -> RepoTreeResult: ...
def select_files_for_analysis(tree: RepoTreeResult, max_files: int = 25, max_file_bytes: int = 100_000) -> List[SelectedFile]: ...
async def fetch_file_contents(client: GitHubClient, owner: str, repo: str, files: List[SelectedFile]) -> Dict[str, str]: ...
def detect_monorepo(tree: RepoTreeResult) -> Tuple[bool, List[str]]: ...  # (is_monorepo, subproject_root_paths)


# linkedin_scraper/github/contributions.py
class ContributionFetcher:
    def __init__(self, client: GitHubClient): ...
    async def fetch(self, username: str, years: int = 2) -> Dict[str, Any]: ...

def normalize_contributions(raw: Dict[str, Any], login: str, org_logins: List[str]) -> ContributionFacts: ...
def compute_contribution_metrics(facts: ContributionFacts) -> DerivedContributionMetrics: ...


# linkedin_scraper/github/ai_analyzer.py
class GitHubAIAnalyzer:
    def __init__(
        self, github_token: Optional[str] = None, llm_client: Optional[LLMClient] = None,
        callback: Optional[ProgressCallback] = None, include_repo_insights: bool = True,
        include_contributions: bool = True, max_repos_for_llm_insights: int = 5,
        contribution_years: int = 2, use_cache: bool = True,
    ): ...
    async def analyze(self, github_url: str) -> CandidateGitHubAIResult: ...
    async def _generate_repo_insights(self, github_facts: GitHubAnalysisResult) -> LLMRepoInsights: ...
    async def _fetch_contributions(self, username: str) -> ContributionFacts: ...
```

### 7.4 Sequencing / dependency order for implementation
1. `models/contributions.py` + `models/ai_insights.py` (no runtime deps, pure schema — write and unit-test first).
2. `llm/base.py`, `llm/anthropic_client.py`, `llm/json_parsing.py`, `llm/prompts.py` (LLM layer, testable with a
   fake `LLMClient` before touching GitHub code at all).
3. `github/queries.py` edit (`CONTRIBUTIONS_QUERY`) + `github/contributions.py` (depends only on existing
   `GitHubClient`, testable against recorded fixtures the same way `fetcher.py` presumably is).
4. `github/repo_analyzer.py` (depends on `GitHubClient` + `hygiene.py` constants — reuse
   `hygiene._MANIFEST_NAMES`/`_CI_NAMES`/`_TEST_DIR_NAMES`, consider promoting these from `_private` to
   public names in `hygiene.py` if reused externally, or add thin public wrapper functions there instead of
   reaching into underscore-prefixed module internals from a new module).
5. `llm/cache.py` (depends on 3+4's output shapes).
6. `github/snapshot.py` additive edit (`build_candidate_llm_snapshot`) — depends on all model layers existing.
7. `github/ai_analyzer.py` orchestrator — wires everything together, last.
8. `core/auth.py` / `core/exceptions.py` / `.env.example` / `setup.py` edits — can happen any time before step 7's
   integration testing.
9. Update `samples/scrape_person.py` (or a new `samples/scrape_person_ai.py`) to demonstrate the new
   `GitHubAIAnalyzer` opt-in path, mirroring the existing `run_github_analysis()` helper.

### 7.5 Explicit tradeoffs/limitations to document in the design doc
- **LLM cost/latency at scale**: analyzing 5 repos/candidate x ~12k input tokens x 1 LLM call each is the default
  cap (`max_repos_for_llm_insights=5`) specifically to bound cost; document the per-candidate token/cost estimate
  and make the cap configurable per caller. Batch/concurrent LLM calls across repos (bounded by a semaphore,
  same `REST_CONCURRENCY=5` pattern) to bound wall-clock latency, not serialize 5 sequential Anthropic calls.
- **`contributionsCollection`'s ~1-year window**: multi-year requires N sequential GraphQL calls (Section 4),
  each consuming rate-limit budget; longer history = more GitHub API cost. Default 2 years, configurable.
- **Private repo/contribution blind spots**: identical caveat to the existing `Limitations` model's
  `contribution_calendar_may_undercount_private_activity` — extend the same philosophy into
  `ContributionLimitations.private_contributions_excluded=True` (always true, non-configurable, since it's a
  GitHub platform constraint, not a pipeline choice).
- **Monorepo file-selection heuristics are approximate**: "manifests at 2+ distinct depths" is a heuristic that
  can both under- and over-detect (e.g. a repo with just a root `pyproject.toml` and one nested test-fixture
  manifest could false-positive) — always exposed as `is_monorepo_guess` (a guess, per naming convention), never
  asserted as fact, and the LLM prompt does not need to trust it blindly (rule 7 in the system prompt).
- **Hallucination risk in `llm_repo_insights`**: mitigated primarily via (a) mandatory per-claim evidence
  citation (Section 3, rule 2; Section 5), (b) `UNKNOWN` band as an explicit escape hatch instead of forced
  guessing, (c) schema validation rejecting non-UNKNOWN bands with zero evidence and forcing a retry
  (`json_parsing.py`), (d) `temperature=0.0` for determinism/reproducibility, (e) never feeding whole repos (less
  surface area for the model to extrapolate beyond what it actually read). None of this eliminates hallucination
  risk entirely — document explicitly that `llm_repo_insights` remains a best-effort, LLM-generated layer and
  should be weighted accordingly by any downstream consumer, unlike the deterministic `github_facts`/
  `deterministic_repo_signals` layers.
- **Provider-agnostic interface, Anthropic-primary**: `LLMClient` ABC decouples `ai_analyzer.py`/`prompts.py`
  from any specific SDK; `AnthropicLLMClient` is the only implementation initially, but a future
  `OpenAILLMClient`/`local model client` could be swapped in via constructor injection
  (`GitHubAIAnalyzer(llm_client=SomeOtherLLMClient())`) without touching orchestration or prompt code. No
  actual failover-between-providers logic is being built now (out of scope per requirements — "keep an
  agnostic interface", not "implement multi-provider failover") — flag this explicitly as a deferred
  enhancement, not a gap.

---

## 8. Final JSON Examples — All Six Layers, One Hypothetical Candidate

Candidate: `jdoe`, repo of interest: `jdoe/task-tracker-api`.

```json
{
  "github_facts": {
    "source_metadata": {
      "input_url_raw": "https://github.com/jdoe",
      "resolved_username": "jdoe",
      "account_type": "USER",
      "fetched_at": "2026-07-05T10:00:00+00:00",
      "api_layers_used": ["graphql", "rest"],
      "authenticated": true
    },
    "parser_metadata": {
      "analyzer_version": "1.0.0",
      "graphql_query_cost": 3,
      "rate_limit_remaining_after": 4980,
      "repos_fetched": 22,
      "repos_hygiene_checked": 22,
      "repos_capped": false
    },
    "profile": {
      "login": "jdoe",
      "name": "Jane Doe",
      "bio": "Backend engineer, distributed systems",
      "followers_count": 84,
      "public_repos_count": 22,
      "account_created_at": "2018-03-14T00:00:00+00:00",
      "organizations": ["open-metrics-collective"],
      "public_contribution_calendar_total": 612
    },
    "repositories": [
      {
        "id": "R_kgD_task_tracker",
        "name": "task-tracker-api",
        "full_name": "jdoe/task-tracker-api",
        "owner_login": "jdoe",
        "owner_type": "USER",
        "is_fork": false,
        "is_archived": false,
        "primary_language": "Python",
        "topics": ["fastapi", "postgres", "task-queue"],
        "stars": 41,
        "pushed_at": "2026-06-20T00:00:00+00:00",
        "has_ci": true,
        "has_tests": true,
        "has_docker": true,
        "has_lint_config": true,
        "has_package_manifest": true,
        "contributors_count": 3,
        "repo_age_days": 512,
        "days_since_last_push": 15,
        "commit_activity_proxy": "ACTIVE_30D",
        "repo_type_guess": "ORIGINAL",
        "is_likely_portfolio_demo": false,
        "hygiene_signals_checked": true
      }
    ],
    "aggregate_features": {
      "total_repos_fetched": 22,
      "original_repos_count": 14,
      "active_repos_90d": 6,
      "total_stars": 210,
      "documentation_coverage_ratio": 0.71,
      "testing_coverage_ratio": 0.64,
      "ci_coverage_ratio": 0.57,
      "top_evidence_repos": ["R_kgD_task_tracker"]
    },
    "llm_snapshot": {
      "login": "jdoe",
      "account_age_years": 8.3,
      "original_repos": 14,
      "top_languages": ["Python", "TypeScript", "Go"],
      "documentation_coverage_ratio": 0.71,
      "testing_coverage_ratio": 0.64,
      "ci_coverage_ratio": 0.57,
      "notable_gaps": []
    },
    "limitations": {
      "hygiene_signals_checked_ratio": 1.0,
      "contribution_calendar_may_undercount_private_activity": true,
      "notes": ["Contribution calendar reflects only activity visible to an unauthenticated GitHub viewer..."]
    }
  },

  "llm_repo_insights": {
    "insights": [
      {
        "repo_id": "R_kgD_task_tracker",
        "repo_full_name": "jdoe/task-tracker-api",
        "repo_summary": "A FastAPI-based REST service for managing task queues, backed by PostgreSQL, with an async worker for background job processing.",
        "workflow_summary": "Requests hit FastAPI route handlers in app/api/routes/, which enqueue jobs via app/queue/producer.py; a separate worker process (worker/main.py) consumes from the queue and writes results back to Postgres via SQLAlchemy models in app/models/.",
        "architecture_summary": "Layered structure: app/api (HTTP layer), app/services (business logic), app/models (ORM), worker/ (background processing) - clear separation, no obvious circular imports observed in sampled files.",
        "libraries_frameworks_used": ["FastAPI", "SQLAlchemy", "Pydantic", "Celery", "pytest"],
        "code_quality": {
          "readability": "HIGH",
          "modularity": "HIGH",
          "project_structure_clarity": "HIGH",
          "dependency_hygiene": "MEDIUM",
          "testing_presence": "MEDIUM",
          "documentation_quality": "MEDIUM",
          "ci_cd_presence": "HIGH",
          "deployability": "HIGH",
          "maintainability_risk_flags": ["dependency_versions_not_pinned_in_requirements.txt"],
          "confidence": "MEDIUM",
          "evidence": [
            {"repo_full_name": "jdoe/task-tracker-api", "path": "requirements.txt", "reason": "dependencies listed without version pins"},
            {"repo_full_name": "jdoe/task-tracker-api", "path": "tests/test_routes.py", "reason": "covers 3 of 8 sampled route handlers"}
          ]
        },
        "engineering_hygiene_notes": ["CI workflow runs lint + pytest on push", "Dockerfile present with multi-stage build"],
        "repo_maturity_guess": "ACTIVE_PROJECT",
        "risk_flags": ["dependency_versions_not_pinned_in_requirements.txt"],
        "confidence": "MEDIUM",
        "evidence_files": [
          {"repo_full_name": "jdoe/task-tracker-api", "path": "app/api/routes/tasks.py", "reason": "primary route handler defining task CRUD workflow"},
          {"repo_full_name": "jdoe/task-tracker-api", "path": ".github/workflows/ci.yml", "reason": "confirms CI runs lint+tests"}
        ],
        "files_analyzed_count": 18,
        "files_truncated": false,
        "is_monorepo_guess": false,
        "llm_model_used": "claude-sonnet-4-5-20250929",
        "generated_at": "2026-07-05T10:02:11+00:00",
        "generation_error": null
      }
    ],
    "limitations": {
      "repos_analyzed_count": 5,
      "repos_skipped_count": 17,
      "repos_skipped_reason": "capped_at_max_repos_for_llm_insights",
      "malformed_json_retry_count": 0,
      "llm_provider": "anthropic",
      "llm_model": "claude-sonnet-4-5-20250929",
      "notes": ["Only the top 5 evidence repos (by recency + hygiene) received LLM-generated insights; the remaining 17 repos have deterministic signals only."]
    }
  },

  "contribution_facts": {
    "login": "jdoe",
    "contribution_period_from": "2024-07-05T00:00:00+00:00",
    "contribution_period_to": "2026-07-05T00:00:00+00:00",
    "total_commit_contributions": 340,
    "total_pull_request_contributions": 58,
    "total_pull_request_review_contributions": 22,
    "total_issue_contributions": 14,
    "total_repository_contributions": 3,
    "contributed_repositories": [
      {
        "repo_full_name": "jdoe/task-tracker-api",
        "owner_login": "jdoe",
        "is_own_repo": true, "is_org_repo": false, "is_external_repo": false,
        "commit_contributions": 210, "pull_request_contributions": 12,
        "pull_request_review_contributions": 0, "issue_contributions": 2
      },
      {
        "repo_full_name": "open-metrics-collective/collector",
        "owner_login": "open-metrics-collective",
        "is_own_repo": false, "is_org_repo": true, "is_external_repo": false,
        "commit_contributions": 90, "pull_request_contributions": 20,
        "pull_request_review_contributions": 15, "issue_contributions": 5
      },
      {
        "repo_full_name": "fastapi/fastapi",
        "owner_login": "fastapi",
        "is_own_repo": false, "is_org_repo": false, "is_external_repo": true,
        "commit_contributions": 0, "pull_request_contributions": 3,
        "pull_request_review_contributions": 1, "issue_contributions": 2,
        "first_contribution_at": "2025-01-10T00:00:00+00:00",
        "last_contribution_at": "2026-05-02T00:00:00+00:00"
      }
    ],
    "external_open_source_repositories": ["fastapi/fastapi"],
    "limitations": {
      "graphql_window_limited_to_one_year": true,
      "contributions_collection_requires_auth": true,
      "private_contributions_excluded": true,
      "partial_fetch": false,
      "rate_limited": false,
      "by_repository_pagination_truncated": false,
      "notes": ["Contribution data assembled from 2 sequential 1-year GraphQL windows (2024-07-05..2025-07-05, 2025-07-05..2026-07-05)."]
    }
  },

  "derived_contribution_metrics": {
    "total_contributed_repos_count": 3,
    "own_repos_count": 1,
    "org_repos_count": 1,
    "external_repos_count": 1,
    "external_repo_ratio": 0.33,
    "external_contribution_share": 0.014,
    "review_to_pr_ratio": 0.33,
    "contribution_consistency": "REGULAR",
    "contribution_recency": "ACTIVE_30D",
    "ecosystem_breadth_count": 2,
    "notable_gaps": []
  },

  "candidate_llm_snapshot": {
    "login": "jdoe",
    "github_facts_snapshot": { "...": "embedded LLMSnapshot.model_dump() from github_facts.llm_snapshot" },
    "top_repo_insights": [ "...single RepoInsight shown above..." ],
    "contribution_summary": { "...": "embedded DerivedContributionMetrics.model_dump() shown above" },
    "combined_notable_gaps": [],
    "combined_limitations_notes": [
      "Only 5 of 22 repos received LLM-generated code insights.",
      "Contribution data covers only the last 2 years and excludes private-repo activity.",
      "This snapshot contains no hiring verdict or quality score; it is a factual, evidence-cited summary for a separate downstream evaluation stage."
    ],
    "generated_at": "2026-07-05T10:03:00+00:00"
  }
}
```

