# Engineering Decisions

## 2026-06-27 — Fix contact info scraping in PersonScraper

**Problem:** `_get_contacts()` returned 0 results despite valid LinkedIn sessions.

**Root causes found:**
1. Direct navigation to `overlay/contact-info/` does not trigger LinkedIn's SPA modal — the page loads the profile without opening the dialog.
2. The original dialog selector (`dialog, [role="dialog"]`) matched ad dialogs, not the contact modal.
3. Contact section labels use `<p>` tags, not `<h3>`/`<h2>` — the old heading selector found nothing.
4. Nested `div[componentkey]` elements caused duplicate contact entries.
5. Website URLs are wrapped in a LinkedIn safety redirect (`/safety/go/?url=...`) that must be unwrapped.

**Decisions:**
- Click the `a[href*="overlay/contact-info"]` link on the profile page instead of navigating directly to the overlay URL.
- Detect the modal using a priority list of selectors: `[data-test-modal]`, `.artdeco-modal`, `dialog`, `[role="dialog"]`, `[aria-label*="contact" i]` — stop at first visible match.
- Parse contact sections by finding `div[componentkey]` elements inside the dialog, then reading the first `<p>` as the label and the second `<p>` as the value.
- Deduplicate contacts using a `(type, value)` seen-set.
- Unwrap LinkedIn safety redirect URLs using `urllib.parse`.

**Files changed:** `linkedin_scraper/scrapers/person.py` — `_get_contacts()` and `_map_contact_heading_to_type()`

---

## 2026-06-27 — Add connected_since contact type

**Decision:** Map "Connected since" labels in the contact dialog to a new `connected_since` contact type (previously unmapped and silently dropped).

---

## 2026-07-05 — Add AI-assisted GitHub analysis layer (repo insights + contribution analysis)

**Goal:** Extend the deterministic `GitHubAnalyzer` pipeline (see `github-analyzer-design.md`) with the
"later, separate LLM evaluation stage" it explicitly reserved — LLM-generated repository insights and
open-source contribution analysis — without changing `GitHubAnalyzer`'s behavior or dependencies.

**Decisions:**
- New `GitHubAIAnalyzer` (`linkedin_scraper/github/ai_analyzer.py`) composes `GitHubAnalyzer` rather than
  adding a flag to it. An LLM/API outage must never fail the deterministic pipeline; keeping them separate
  means callers who only want `github_facts` pay no new dependency, latency, or failure mode.
- LLM provider is Anthropic (`anthropic` SDK) behind a provider-agnostic `LLMClient` ABC
  (`linkedin_scraper/llm/base.py`), so a different provider can be swapped in via constructor injection
  without touching orchestration or prompt code.
- Repo-insight generation is capped at the top 5 evidence repos per candidate (`max_repos_for_llm_insights`)
  to bound LLM cost/latency; every claim in the LLM output must cite an `evidence_files` entry, and banded
  fields (readability, modularity, etc.) use `LOW/MEDIUM/HIGH/UNKNOWN` — never a single scalar score —
  matching the existing codebase's `_guess`/`_raw` non-verdict discipline. Schema validation
  (`llm/json_parsing.py`) rejects a non-`UNKNOWN` band with zero evidence and retries once.
- Contribution analysis (`linkedin_scraper/github/contributions.py`) uses GitHub's
  `contributionsCollection` GraphQL field, which only accepts a 1-year window; multi-year history is
  approximated by issuing the query N times with sequential 1-year windows and merging results
  (`contribution_years`, default 2). Own/org/external repo classification uses the profile's
  `organizations` list already fetched by the existing `PROFILE_AND_REPOS_QUERY`.
- Full design at `github-analyzer-ai-design.md`.

**Environment/runtime issue found (not a code bug):** on this machine, Python's `httpx`/`anthropic` SDK
failed all calls to `api.anthropic.com` with `SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer
certificate`, while `curl` to the same host succeeded and `httpx` calls to `api.github.com` also succeeded.
Root cause: Python's bundled `certifi` root store was missing an intermediate CA that macOS's Keychain
(used by `curl`) already trusts. Fix: `pip install pip-system-certs`, which patches Python's `ssl` module to
use the OS trust store instead of `certifi`. This is a one-time local environment fix, not something the
pipeline can work around in code — `GitHubAIAnalyzer` already degrades a failed LLM call to
`RepoInsight.generation_error` per-repo rather than crashing, which is exactly what surfaced this cleanly.

**Files changed:** `linkedin_scraper/models/ai_insights.py`, `linkedin_scraper/models/contributions.py`,
`linkedin_scraper/models/__init__.py`, `linkedin_scraper/llm/` (new package), `linkedin_scraper/github/ai_analyzer.py`,
`linkedin_scraper/github/repo_analyzer.py`, `linkedin_scraper/github/contributions.py`,
`linkedin_scraper/github/queries.py` (+`CONTRIBUTIONS_QUERY`), `linkedin_scraper/github/snapshot.py`
(+`build_candidate_llm_snapshot`), `linkedin_scraper/github/__init__.py`, `linkedin_scraper/core/auth.py`
(+`load_anthropic_key_from_env`), `linkedin_scraper/core/exceptions.py` (+`LLMError`,
`LLMResponseParsingError`), `.env.example`, `setup.py`, `requirements.txt`, `samples/scrape_person.py`.

---

## 2026-07-15 — Deterministic career timeline; trim GitHub analysis to top-5 tech + unlisted projects/portfolio; streamline readiness inputs

**Problem:** Three compounding sources of noise in the pipeline output:
1. There was no unified career timeline — `Person.experiences` and `Person.educations` were two disjoint,
   unsorted lists. The only "tagging" was an LLM call (`journey_tagger.py`) that force-fit every *experience*
   into one of 4 prose-defined kinds (promotion/transition/function/pivot); it never saw education at all, and
   didn't distinguish education/internship/full-time/contract — the classification the business actually
   needs. Meanwhile LinkedIn's own employment-type string (Full-time/Internship/Contract/etc.), which would
   trivially answer that question, was computed during scraping purely to detect a grouped-vs-single HTML
   card layout and then thrown away (`scrapers/person.py`).
2. `GitHubAIAnalyzer` produced far more than needed for candidate review: full per-repo hygiene signals,
   LLM-generated repo insights (summaries, architecture, Mermaid diagrams, code-quality bands) for up to 5
   repos, and multi-year contribution analysis. The actual ask is narrow: top-5 technologies/frameworks used,
   which GitHub projects aren't already mentioned in the resume/LinkedIn (surfaced with a link), and whether
   the GitHub profile has a personal portfolio/website not already listed elsewhere (the profile's
   `website_url`/`blog` field was already fetched but never surfaced anywhere downstream).
3. Readiness evaluation's prompt-building and the headhunt-G export both depended directly on the above two
   sprawling/ungrounded shapes.

**Decisions:**

*Career timeline (fully deterministic — no LLM):*
- Deleted `models/journey.py`, `evaluation/journey_tagger.py`, `evaluation/journey_prompts.py` and the
  `--no-journey-tags` flag/call site in `samples/export_to_headhunt.py`. Classification of career-transition
  kind is now derivable from data the pipeline already has (company-change, title-change, LinkedIn's own
  employment-type label) — an LLM call added latency/cost/failure-mode for no precision gain over rules.
- New `Experience.employment_type` field (`models/person.py`) — threads through the employment-type string
  `scrapers/person.py` already parses to distinguish grouped vs single-role HTML cards, instead of discarding
  it.
- New `models/timeline.py` (`CareerTimeline`, `TimelineEntry`, `TimelineEntryKind`, `TimelineTransitionKind`)
  and `evaluation/timeline_builder.py` (`build_career_timeline`): merges experiences + educations into one
  chronologically-sorted (oldest→newest) list. `kind` maps directly from `employment_type` (never guessed —
  `"unknown"` when LinkedIn doesn't expose it); `transition` is `first_role`/`promotion`/`transition`/
  `function_change` from comparing institution/title against the previous *work* entry in chronological
  order; education entries are always `kind="education"`, `transition=None`.
- `export/headhunt_adapter.py` (`map_experiences`/`map_education`/`map_candidate_profile`) and
  `evaluation/prompts.py` (`_render_person_block`) now build/consume this `CareerTimeline` internally instead
  of taking a separately-computed, index-aligned tag list — removes a class of bugs where the tag list could
  silently drift out of alignment with the experience list it was zipped against.

*GitHub analysis (trimmed, deterministic):*
- Commented out (not deleted) the LLM repo-insight generation and contribution-analysis call sites in
  `github/ai_analyzer.py`, each with a `# Disabled: ...` marker, so re-enabling later is a two-line uncomment.
  `features.py`'s top-languages/top-frameworks caps dropped from 8/15 to 5; the topics rollup is disabled
  entirely (out of scope for "technologies/frameworks").
- New `models.github.GitHubCandidateSummary` + `github/candidate_summary.py`
  (`build_candidate_github_summary`): top-5 merged technologies (languages + frameworks interleaved by rank,
  deduped case-insensitively), `unlisted_projects` (non-fork repos not already referenced in the
  resume/LinkedIn — checked by normalized URL exact-match first, then fuzzy match: token-overlap against
  resume raw text/LinkedIn about, and `difflib.SequenceMatcher` ratio ≥0.6 against resume project names and
  LinkedIn accomplishments tagged `category="project"`), and `unlisted_portfolio_url` (the GitHub profile's
  `website_url`, surfaced only if it doesn't already match a resume link or LinkedIn contact). Kept the
  legitimately useful deterministic activity ratios (original-repo count, 90-day activity, doc/test/CI
  coverage, account age) — those aren't the "bloat," the AI-generated narrative layer was.
- `ReadinessEvaluator.evaluate()`'s `github_result` parameter, `evaluation/prompts.py`'s GitHub rendering
  block, `sourcing/skills.py`'s `aggregate_skills()`, and `export/headhunt_adapter.py`'s
  `map_skill_groups`/`map_projects_from_github`/`map_external_sources` all switched from the old
  `CandidateGitHubAIResult` to `GitHubCandidateSummary`. `map_projects_from_github` now surfaces
  `unlisted_projects` first (genuinely new information) and only fills remaining slots with top-starred repos
  if there's room left under the existing 6-project cap.
- Added LinkedIn Skills scraping (`PersonScraper._get_skills`, new `Person.skills` field) at the same time,
  since `sourcing/skills.py` previously had no LinkedIn-sourced skill signal at all — it now merges LinkedIn
  skills, resume skills/projects, and GitHub top technologies (new `SOURCE_LINKEDIN_SKILL`/
  `SOURCE_GITHUB_TECHNOLOGY` source tags, replacing the separate language/framework/topic source tags).
- `scripts/run_readiness_from_log.py` (log-replay dev utility) updated to match: dropped the
  `candidate_llm_snapshot`/contribution-facts log-parsing block (that data is no longer printed by
  `scrape_person.py`/`run_pipeline.py`) and now reconstructs a `GitHubCandidateSummary` via
  `build_candidate_github_summary` from the parsed `github_facts`.

**Files changed:** `linkedin_scraper/models/person.py` (+`employment_type`, +`skills`),
`linkedin_scraper/models/timeline.py` (new), `linkedin_scraper/evaluation/timeline_builder.py` (new),
`linkedin_scraper/models/journey.py` / `evaluation/journey_tagger.py` / `evaluation/journey_prompts.py`
(deleted), `linkedin_scraper/scrapers/person.py` (+`_get_skills`, employment_type threading),
`linkedin_scraper/models/github.py` (+`GitHubCandidateSummary`, +`UnlistedProject`),
`linkedin_scraper/github/candidate_summary.py` (new), `linkedin_scraper/github/ai_analyzer.py`,
`linkedin_scraper/github/features.py`, `linkedin_scraper/evaluation/evaluator.py`,
`linkedin_scraper/evaluation/prompts.py`, `linkedin_scraper/export/headhunt_adapter.py`,
`linkedin_scraper/sourcing/skills.py`, `samples/scrape_person.py`, `samples/export_to_headhunt.py`,
`scripts/run_pipeline.py`, `scripts/run_readiness_from_log.py`, plus new/updated tests
(`tests/test_timeline_builder.py`, `tests/test_github_candidate_summary.py`,
`tests/test_headhunt_adapter.py`, `tests/test_sourcing_skills.py`, `tests/test_evaluator.py`,
`tests/test_person_scraper.py`).
