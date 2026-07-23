# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"
playwright install chromium

# Run unit tests only (no LinkedIn session needed)
pytest -m unit

# Run integration tests (requires linkedin_session.json at repo root)
pytest -m integration

# Run a single test file
pytest tests/test_person_scraper.py

# Create a LinkedIn session before integration testing
python samples/create_session.py
```

## Architecture

`linkedin_scraper` is an async Playwright-based library (v3, fully rewritten from v2's Selenium). All public API is `async`/`await`.

### Entry points

- `BrowserManager` (`core/browser.py`) — async context manager wrapping Playwright lifecycle. Holds `page`, `context`, `browser`. Sessions are persisted to/from a JSON file via `save_session` / `load_session`.
- Auth helpers (`core/auth.py`) — `login_with_credentials`, `login_with_cookie`, `wait_for_manual_login`, `is_logged_in`. `warm_up_browser` visits neutral sites before LinkedIn to reduce checkpoint triggers.

### Scrapers (`scrapers/`)

All scrapers inherit `BaseScraper` (`scrapers/base.py`), which wraps common Playwright operations (scroll, click-see-more, modal close, safe text extraction, `retry_async`). Each scraper takes a `page: Page` and optional `ProgressCallback`.

| Scraper | Target |
|---|---|
| `PersonScraper` | Profile: name, headline, location, about, experience, education, skills, accomplishments, contacts |
| `CompanyScraper` | Company overview, industry, size, HQ |
| `CompanyPostsScraper` | Posts feed with reaction/comment/repost counts |
| `JobScraper` | Single job listing detail |
| `JobSearchScraper` | Job search results |

**Contact info quirk** (see `DECISIONS.md`): the contact-info overlay must be opened by clicking `a[href*="overlay/contact-info"]` on the profile page — direct URL navigation does not trigger LinkedIn's SPA modal. Modal is detected via a priority list: `[data-test-modal]`, `.artdeco-modal`, `dialog`, `[role="dialog"]`, `[aria-label*="contact" i]`. LinkedIn safety redirect URLs (`/safety/go/?url=...`) are unwrapped with `urllib.parse`.

### Callbacks (`callbacks.py`)

`ProgressCallback` is an abstract base with `on_start`, `on_progress`, `on_complete`, `on_error`. Built-in: `SilentCallback` (default), `ConsoleCallback`, `JSONLogCallback`, `MultiCallback`.

### Models (`models/`)

Pydantic v2 models: `Person`, `Experience`, `Education`, `Contact`, `Accomplishment`, `Interest`, `Company`, `CompanySummary`, `Employee`, `Job`, `Post`, `ResumeData`.

GitHub candidate analysis models (`models/github.py`, `models/contributions.py`, `models/ai_insights.py`) are layered and never mixed: raw/normalized facts → derived aggregate features → LLM snapshot, plus two more layers for AI-assisted analysis (see below). None of these render a hiring verdict or single quality score — see `github-analyzer-design.md` and `github-analyzer-ai-design.md`.

### GitHub candidate analysis (`github/`)

Two entry points, deliberately separate:

- `GitHubAnalyzer` (`github/analyzer.py`) — deterministic, non-judgmental pipeline: GitHub URL → `GitHubAnalysisResult` (profile, repositories, aggregate features, `LLMSnapshot`, `Limitations`). GraphQL-primary (`queries.py`), REST-secondary for hygiene signals (CI/tests/docker/lint/manifest via `hygiene.py`). No LLM/network-to-Anthropic dependency; works with just `GITHUB_TOKEN` (or degrades to unauthenticated REST without one).
- `GitHubAIAnalyzer` (`github/ai_analyzer.py`) — composes `GitHubAnalyzer` and adds two best-effort stages: LLM-generated repo insights (`github/repo_analyzer.py` for file selection/tree/content fetch + `llm/` package for prompting/parsing) and open-source contribution analysis (`github/contributions.py`, using GitHub's `contributionsCollection` GraphQL field). An LLM/API failure here degrades that one repo's insight (`RepoInsight.generation_error`) rather than failing the whole pipeline — `GitHubAnalyzer`'s output is never affected by AI-layer failures. Full design at `github-analyzer-ai-design.md`.

### LLM client (`llm/`)

Provider-agnostic `LLMClient` ABC (`llm/base.py`) with `AnthropicLLMClient` (`llm/anthropic_client.py`) as the only implementation; swap providers via constructor injection into `GitHubAIAnalyzer(llm_client=...)`. `llm/prompts.py` holds the repo-insight prompt templates (evidence-citation required, banded fields only, no verdicts). `llm/json_parsing.py` validates and retries malformed/schema-invalid LLM JSON responses once before raising `LLMResponseParsingError`.

### Tests

Tests are split by marker:
- `unit` — no network, no session required
- `integration` — require `linkedin_session.json` at repo root (auto-skipped if missing)

`conftest.py` provides `browser` and `browser_with_session` fixtures; the latter skips if no session file exists. Integration tests always run `headless=False` — LinkedIn blocks or degrades in headless mode.

## Authentication flow

1. Run `samples/create_session.py` → manual login → saves `linkedin_session.json`
2. All scrapers load session via `browser.load_session("linkedin_session.json")`
3. Credentials via env: `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD` (loaded from `.env` by `load_credentials_from_env`)

## Environment variables (all loaded from `.env` via `core/auth.py`; see `.env.example` for where to get each one)

| Variable | Loader | Used by | Required? |
|---|---|---|---|
| `LINKEDIN_EMAIL` / `LINKEDIN_USERNAME`, `LINKEDIN_PASSWORD` | `load_credentials_from_env()` | LinkedIn login | Required for LinkedIn scraping |
| `GITHUB_TOKEN` | `load_github_token_from_env()` | `GitHubAnalyzer`, `GitHubAIAnalyzer` | Optional but strongly recommended — GraphQL requires auth (401 unauthenticated); without it, both analyzers fall back to unauthenticated REST at 60 req/hr and `GitHubAIAnalyzer`'s contribution analysis is skipped entirely (`contributionsCollection` is GraphQL-only) |
| `ANTHROPIC_API_KEY` | `load_anthropic_key_from_env()` | `GitHubAIAnalyzer` (repo insight generation only) | Optional — without it, repo insight generation is skipped but `github_facts`/contribution analysis still run |

Run `python samples/scrape_person.py --github <url>` (optionally with `--resume`/`--url`) to exercise the full pipeline end to end; use `--no-repo-insights` / `--no-contributions` to isolate stages.

**Known environment gotcha:** on some macOS Python installs, calls to `api.anthropic.com` fail with `SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate` even though `curl`/GitHub API calls succeed — `certifi`'s bundled root store is missing an intermediate CA that the OS Keychain already trusts. Fix: `pip install pip-system-certs` (patches Python's `ssl` module to use the OS trust store). See `DECISIONS.md` (2026-07-05 entry).
