# LinkedIn Scraper & Candidate Sourcing Console

[![PyPI version](https://badge.fury.io/py/linkedin-scraper.svg)](https://badge.fury.io/py/linkedin-scraper)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Async LinkedIn scraper built with Playwright for extracting profile, company, and job data from LinkedIn — plus a candidate-sourcing pipeline built on top of it: Google X-ray search via Serper.dev, a CrewAI multi-agent search-and-review crew (a LinkedIn Searcher agent, a Google Searcher agent, and an Authority Reviewer agent that merges/dedupes/shortlists their output), and a local web console (FastAPI + React) with a classic search form and an AI chat assistant. Everything is also drivable from the CLI (`samples/*.py`) without the web app. See [CLAUDE.md](CLAUDE.md) for the full architecture.

**New here?** Jump to [Setup](#setup) for the full install process, or straight to [Web Console Setup](#web-console-setup-backend--frontend) if you just want the backend/frontend running.

## ⚠️ Breaking Changes in v3.0.0

**Version 3.0.0 introduces breaking changes and is NOT backwards compatible with previous versions.**

### What Changed:
- **Playwright instead of Selenium** - Complete rewrite using Playwright for better performance and reliability
- **Async/await throughout** - All methods are now async and require `await`
- **New package structure** - Imports have changed (e.g., `from linkedin_scraper import PersonScraper`)
- **Updated data models** - Using Pydantic models instead of simple objects
- **Different API** - Method signatures and return types have changed

### Migration Guide:

**Before (v2.x with Selenium):**
```python
from linkedin_scraper import Person

person = Person("https://linkedin.com/in/username", driver=driver)
print(person.name)
```

**After (v3.0+ with Playwright):**
```python
import asyncio
from linkedin_scraper import BrowserManager, PersonScraper

async def main():
    async with BrowserManager() as browser:
        await browser.load_session("session.json")
        scraper = PersonScraper(browser.page)
        person = await scraper.scrape("https://linkedin.com/in/username")
        print(person.name)

asyncio.run(main())
```

**If you need the old Selenium-based version:**
```bash
pip install linkedin-scraper==2.11.2
```
## Setup

These steps get the whole project running: the core scraper library, the X-ray/CrewAI candidate-sourcing pipeline, and (optionally) the web console. Skip whatever you don't need — none of the pieces below require the others.

### 1. Prerequisites

- Python 3.10+ (3.11 recommended)
- Node.js 18+ and npm — only needed for the web console's frontend
- A LinkedIn account, for session-based scraping
- API keys for whichever features you want (step 3)

### 2. Clone and install Python dependencies

```bash
git clone https://github.com/GaayanVerma/headhunt.git
cd headhunt
pip install -e ".[dev]"
playwright install chromium
```

Add optional extras as needed — they can be combined, e.g. `pip install -e ".[dev,export,crew,web]"`:

| Extra | Adds | Needed for |
|---|---|---|
| `export` | `openpyxl` | Excel export of candidate search results |
| `crew` | `crewai` | The AI chat assistant's candidate search (LinkedIn Searcher + Google Searcher + Authority Reviewer agents) |
| `web` | `fastapi`, `uvicorn` | The local web console's backend |

### 3. Configure environment variables

```bash
cp .env.example .env
```

Fill in `.env` with whichever keys the features you want require — see `.env.example` for exact instructions and where to get each one:

| Variable | Needed for |
|---|---|
| `LINKEDIN_EMAIL` / `LINKEDIN_USERNAME`, `LINKEDIN_PASSWORD` | Programmatic LinkedIn login (optional — the manual session login in step 4 doesn't need this) |
| `SERPER_API_KEY` | X-ray candidate discovery (`search_xray_jd.py`) — required, no fallback |
| `ANTHROPIC_API_KEY` | LLM JD-signal extraction, the CrewAI sourcing crew, GitHub AI insights, and the web console's chat assistant |
| `GITHUB_TOKEN` | GitHub candidate analysis (optional but strongly recommended — GraphQL requires auth) |

### 4. Create a LinkedIn session

Most scraping (profile/company/job scraping, LinkedIn people search, X-ray's `--enrich-top`) needs an authenticated session:

```bash
python samples/create_session.py
```

This opens a real, visible browser window — log in manually and it saves `linkedin_session.json` at the repo root. That file is gitignored and never committed; it's your own session, not something to check in or share.

### 5. (Optional) Set up the web console frontend

Only needed for the classic-search-form + AI-chat web UI — skip this if you're driving everything from the CLI:

```bash
cd frontend
npm install
```

### 6. Run it

**CLI — X-ray candidate search:**
```bash
python samples/search_xray_jd.py --jd-file jd.txt
```

**CLI — the CrewAI dual-searcher + authority-reviewer crew:**
```bash
python samples/run_sourcing_crew.py --jd-file jd.txt
```

**Web console** (needs the `web` extra installed and the frontend set up):
```bash
# terminal 1
uvicorn backend.main:app --reload --port 8000
# terminal 2
cd frontend && npm run dev
```
Then open http://localhost:5173 — `/` is the classic search form, `/chat` is the AI assistant. This is a **local-only app** by design: classic LinkedIn scraping needs a real, visible browser window, which only works reliably headed and only makes sense on the machine you're sitting at.

**Non-technical setup (macOS):** skip steps 1–6 above and double-click **`Start Console.command`** at the repo root instead (first run: right-click → Open, since it's from an unidentified developer). It installs Homebrew/Python/Node/dependencies/Chromium if missing, prompts you to fill in `.env`, then starts both servers and opens the app in your browser. Safe to re-run any time. See `scripts/start_console.sh` for what it does.

**Tests:**
```bash
pytest -m unit          # no network/session required
pytest -m integration   # requires linkedin_session.json, auto-skipped if missing
```

---

## Web Console Setup (Backend + Frontend)

The web console is a local-only app: a FastAPI backend and a React (Vite) frontend, run as two separate processes on your own machine. It's local-only by design — classic LinkedIn scraping needs a real, visible browser window, which only works headed and only makes sense on the machine you're sitting at.

### Backend (`backend/`, FastAPI)

```bash
pip install -e ".[web]"          # or combine with other extras, e.g. ".[dev,web,crew,export]"
uvicorn backend.main:app --reload --port 8000
```

- Serves the API at `http://127.0.0.1:8000` — interactive docs at `http://127.0.0.1:8000/docs`
- Requires `.env` to be configured (see [Setup](#setup) step 3) — `SERPER_API_KEY` for the classic search's X-ray discovery, `ANTHROPIC_API_KEY` for the chat assistant, and the `crew` extra installed for the chat's candidate-search tool
- CORS is scoped to `http://localhost:5173` (the Vite dev server) only — not open to arbitrary origins
- Layout: `backend/main.py` (app + router registration), `backend/jobs.py` (the in-memory background-job store every long-running operation goes through), `backend/routers/` (`xray.py` classic search, `session.py` LinkedIn login/status, `chat.py` AI assistant), `backend/services/` (`scraping.py` classic scrape wrappers, `crew_search.py` wraps `linkedin_scraper/crew/`, `chat_agent.py`/`chat_tools.py` the chat's tool-use loop)

### Frontend (`frontend/`, React + Vite)

```bash
cd frontend
npm install
npm run dev
```

- Opens at `http://localhost:5173` — `vite.config.ts` proxies `/api` and `/files` to the backend at `127.0.0.1:8000`, so the backend must already be running
- `npm run build` produces a production build in `frontend/dist/` (not committed — see `.gitignore`)
- Layout: `src/pages/ClassicSearch.tsx` (the flag-driven form), `src/pages/ChatAssistant.tsx` (the AI chat), `src/components/` (shared `CandidateTable`, `JobProgress` job-polling, `SessionStatusBadge`), `src/api/client.ts` (typed fetch wrapper mirroring the backend's schemas), `src/hooks/useChat.ts` (chat state + job-completion polling)

Run both together (backend in one terminal, frontend in another) and open `http://localhost:5173` — `/` is the classic search form, `/chat` is the AI assistant.

---

## Features

- **Person Profiles** - Scrape comprehensive profile information
  - Basic info (name, headline, location, about)
  - Work experience with details
  - Education history
  - Skills and accomplishments
  
- **Company Pages** - Extract company information
  - Company overview and details
  - Industry and size
  - Headquarters location
  
- **Company Posts** - Scrape posts from company pages
  - Post content and text
  - Reactions, comments, reposts counts
  - Posted date and images
  
- **Job Listings** - Scrape job postings
  - Job details and requirements
  - Company information
  - Application links

- **Async/Await** - Modern async Python with Playwright
- **Type Safety** - Full Pydantic models for all data
- **Progress Callbacks** - Track scraping progress
- **Session Management** - Reuse authenticated sessions

## Candidate Sourcing (X-ray Search, CrewAI Crew, Web Console)

Built on top of the scraper library above, `sourcing/` turns a job description into a ranked candidate list without needing LinkedIn's own (rate-limited, checkpoint-prone) people-search UI:

- **X-ray search** (`samples/search_xray_jd.py`) — free-text JD → LLM-extracted `JDSignals` → `site:linkedin.com/in/` Google boolean queries run through Serper.dev → scored, ranked, exported to Excel. No LinkedIn session needed for discovery itself.
- **CrewAI sourcing crew** (`samples/run_sourcing_crew.py`, `linkedin_scraper/crew/`) — a LinkedIn Searcher agent and a Google Searcher agent search independently, and an Authority Reviewer agent merges, dedupes, quality-bars, and shortlists their combined output before it reaches you.
- **Web console** (`backend/` + `frontend/`) — a local FastAPI + React app with two views: a classic form exposing every X-ray flag, and an AI chat assistant (native Claude tool-use) that runs the same crew conversationally, asks clarifying questions before an expensive search, and answers only from what the tools actually returned.

See the [Setup](#setup) section above to get any of these running, and [CLAUDE.md](CLAUDE.md) for the full architecture writeup.

## Installation

For local development of this repo, use the editable install from [Setup](#setup) above (`pip install -e ".[dev]"`), not the PyPI package — this fork adds the sourcing pipeline, crew, and web console on top of the published `linkedin-scraper` package.

If you only want the base scraper library as a dependency in another project:

```bash
pip install linkedin-scraper
```

### Install Playwright browsers:

```bash
playwright install chromium
```

## Quick Start

### Basic Usage

```python
import asyncio
from linkedin_scraper import BrowserManager, PersonScraper

async def main():
    # Initialize browser
    async with BrowserManager(headless=False) as browser:
        # Load authenticated session
        await browser.load_session("session.json")
        
        # Create scraper
        scraper = PersonScraper(browser.page)
        
        # Scrape a profile
        person = await scraper.scrape("https://linkedin.com/in/williamhgates/")
        
        # Access data
        print(f"Name: {person.name}")
        print(f"Headline: {person.headline}")
        print(f"Location: {person.location}")
        print(f"Experiences: {len(person.experiences)}")
        print(f"Education: {len(person.educations)}")

asyncio.run(main())
```

### Company Scraping

```python
from linkedin_scraper import CompanyScraper

async def scrape_company():
    async with BrowserManager(headless=False) as browser:
        await browser.load_session("session.json")
        
        scraper = CompanyScraper(browser.page)
        company = await scraper.scrape("https://linkedin.com/company/microsoft/")
        
        print(f"Company: {company.name}")
        print(f"Industry: {company.industry}")
        print(f"Size: {company.company_size}")
        print(f"About: {company.about_us[:200]}...")

asyncio.run(scrape_company())
```

### Job Scraping

```python
from linkedin_scraper import JobSearchScraper

async def search_jobs():
    async with BrowserManager(headless=False) as browser:
        await browser.load_session("session.json")
        
        scraper = JobSearchScraper(browser.page)
        jobs = await scraper.search(
            keywords="Python Developer",
            location="San Francisco",
            limit=10
        )
        
        for job in jobs:
            print(f"{job.title} at {job.company}")
            print(f"Location: {job.location}")
            print(f"Link: {job.linkedin_url}")
            print("---")

asyncio.run(search_jobs())
```

### Company Posts Scraping

```python
from linkedin_scraper import BrowserManager, CompanyPostsScraper

async def scrape_company_posts():
    async with BrowserManager(headless=False) as browser:
        await browser.load_session("session.json")
        
        scraper = CompanyPostsScraper(browser.page)
        posts = await scraper.scrape(
            "https://linkedin.com/company/microsoft/",
            limit=10
        )
        
        for post in posts:
            print(f"Posted: {post.posted_date}")
            print(f"Text: {post.text[:200]}...")
            print(f"Reactions: {post.reactions_count}")
            print(f"Comments: {post.comments_count}")
            print(f"URL: {post.linkedin_url}")
            print("---")

asyncio.run(scrape_company_posts())
```

## Authentication

LinkedIn requires authentication. You need to create a session file first:

### Option 1: Manual Login Script

```python
from linkedin_scraper import BrowserManager, wait_for_manual_login

async def create_session():
    async with BrowserManager(headless=False) as browser:
        # Navigate to LinkedIn
        await browser.page.goto("https://www.linkedin.com/login")
        
        # Wait for manual login (opens browser)
        print("Please log in to LinkedIn...")
        await wait_for_manual_login(browser.page, timeout=300)
        
        # Save session
        await browser.save_session("session.json")
        print("✓ Session saved!")

asyncio.run(create_session())
```

### Option 2: Programmatic Login

```python
from linkedin_scraper import BrowserManager, login_with_credentials
import os

async def login():
    async with BrowserManager(headless=False) as browser:
        # Login with credentials
        await login_with_credentials(
            browser.page,
            username=os.getenv("LINKEDIN_EMAIL"),
            password=os.getenv("LINKEDIN_PASSWORD")
        )
        
        # Save session for reuse
        await browser.save_session("session.json")

asyncio.run(login())
```

## Progress Tracking

Track scraping progress with callbacks:

```python
from linkedin_scraper import ConsoleCallback, PersonScraper

async def scrape_with_progress():
    callback = ConsoleCallback()  # Prints progress to console
    
    async with BrowserManager(headless=False) as browser:
        await browser.load_session("session.json")
        
        scraper = PersonScraper(browser.page, callback=callback)
        person = await scraper.scrape("https://linkedin.com/in/williamhgates/")

asyncio.run(scrape_with_progress())
```

### Custom Callbacks

```python
from linkedin_scraper import ProgressCallback

class MyCallback(ProgressCallback):
    async def on_start(self, scraper_type: str, url: str):
        print(f"Starting {scraper_type} scraping: {url}")
    
    async def on_progress(self, message: str, percent: int):
        print(f"[{percent}%] {message}")
    
    async def on_complete(self, scraper_type: str, url: str):
        print(f"Completed {scraper_type}: {url}")
    
    async def on_error(self, error: Exception):
        print(f"Error: {error}")
```

## Data Models

All scraped data is returned as Pydantic models:

### Person

```python
class Person(BaseModel):
    name: str
    headline: Optional[str]
    location: Optional[str]
    about: Optional[str]
    linkedin_url: str
    experiences: List[Experience]
    educations: List[Education]
    skills: List[str]
    accomplishments: Optional[Accomplishment]
```

### Company

```python
class Company(BaseModel):
    name: str
    industry: Optional[str]
    company_size: Optional[str]
    headquarters: Optional[str]
    founded: Optional[str]
    specialties: List[str]
    about: Optional[str]
    linkedin_url: str
```

### Job

```python
class Job(BaseModel):
    title: str
    company: str
    location: Optional[str]
    description: Optional[str]
    employment_type: Optional[str]
    seniority_level: Optional[str]
    linkedin_url: str
```

### Post

```python
class Post(BaseModel):
    linkedin_url: Optional[str]
    urn: Optional[str]
    text: Optional[str]
    posted_date: Optional[str]
    reactions_count: Optional[int]
    comments_count: Optional[int]
    reposts_count: Optional[int]
    image_urls: List[str]
```

## Advanced Usage

### Browser Configuration

```python
browser = BrowserManager(
    headless=False,  # Show browser window
    slow_mo=100,     # Slow down operations (ms)
    viewport={"width": 1920, "height": 1080},
    user_agent="Custom User Agent"
)
```

### Error Handling

```python
from linkedin_scraper import (
    AuthenticationError,
    RateLimitError,
    ProfileNotFoundError
)

try:
    person = await scraper.scrape(url)
except AuthenticationError:
    print("Not logged in - session expired")
except RateLimitError:
    print("Rate limited by LinkedIn")
except ProfileNotFoundError:
    print("Profile not found or private")
```

## Best Practices

1. **Rate Limiting** - Add delays between requests
   ```python
   import asyncio
   await asyncio.sleep(2)  # 2 second delay
   ```

2. **Session Reuse** - Save and reuse sessions to avoid frequent logins

3. **Error Handling** - Always handle exceptions (rate limits, auth errors, etc.)

4. **Headless Mode** - Use `headless=False` during development, `True` for production

5. **Respect LinkedIn** - Don't scrape aggressively, respect rate limits

## Requirements

- Python 3.8+ (3.10+ for the sourcing pipeline; 3.11 recommended)
- Playwright
- Pydantic 2.0+
- aiofiles
- python-dotenv (optional, for credentials)
- Optional, per feature (see [Setup](#setup)): `openpyxl` (Excel export), `crewai` (sourcing crew), `fastapi`/`uvicorn` (web console backend), Node.js 18+/npm (web console frontend)

## License

Apache License 2.0 - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This tool is for educational purposes only. Make sure to comply with LinkedIn's Terms of Service and use responsibly. The authors are not responsible for any misuse of this tool.

## Links

- [This repository](https://github.com/GaayanVerma/headhunt) — candidate-sourcing pipeline, CrewAI crew, and web console
- [Upstream scraper library](https://github.com/joeyism/linkedin_scraper) — the base Playwright/async LinkedIn scraper this project builds on
- [PyPI Package](https://pypi.org/project/linkedin-scraper/)
