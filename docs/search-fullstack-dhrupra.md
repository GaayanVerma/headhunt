# `search_fullstack_dhrupra.py` — Logic & Design

`samples/search_fullstack_dhrupra.py` searches LinkedIn for full stack developer
candidates and exports a ranked Excel/JSON. It's tailored to one JD: the Dhrupra
Services Pvt. Ltd. Full Stack Developer role (React 18 + TypeScript, Node.js/Express,
SQL + NoSQL, 1-3 YOE). Location is not filtered or scored — candidates from anywhere
are considered.

## Pipeline

1. **Search** — runs 8 different LinkedIn people-search queries (`DEFAULT_SEARCHES`),
   not just one. Each query returns up to `--per-query` results, paginating up to
   `--max-pages`.
2. **Deduplicate** — merges results across all queries into one dict keyed by
   `linkedin_url`, since the same person often surfaces under multiple queries.
3. **Score** — every unique candidate is scored against the JD via `rank_candidates`
   (defined locally in the script, not the shared `linkedin_scraper/sourcing/scoring.py`
   module — that module's `JD_SIGNALS` are pinned to a different JD and role), using
   only the fields available from a search-result card: name, headline, location,
   connection degree. No profile-detail scraping happens here — it's a coarse, cheap
   pre-filter.
4. **Filter + rank** — sorted by score descending, cut to `--min-score` (default 15),
   `--min-years`/`--max-years` (default 1-3, matching the JD band), and `--limit`
   (default 250).
5. **Export** — writes Excel + JSON, plus prints a top-10 preview.

## Why 8 separate queries, not one

Recruiters searching by title alone under-sample. The list mixes:

| Query | Why it's there |
|---|---|
| `full stack developer react node` | Direct title + stack match |
| `react developer typescript` | Catches frontend-leaning candidates the JD's "not optional" TypeScript requirement should surface |
| `node.js developer express` | Catches backend-leaning candidates on the JD's Express requirement |
| `frontend developer react typescript` | Alternate title phrasing for the same frontend skillset |
| `backend developer node express postgresql` | JD requires SQL — Postgres is a common signal for that stack |
| `full stack engineer react node mongodb` | Catches the JD's NoSQL requirement (MongoDB is the common NoSQL choice for this stack) |
| `javascript developer react node express` | Broader JS-title catch for people who don't self-describe as "full stack" |
| `software engineer react node sql` | Generic title, stack-constrained — catches people with the right stack under a generic title |

## Scoring logic (defined in the script)

A weighted keyword match over `name + headline + location` — not an LLM judgment:

- **`react_typescript` (15 pts)** and **`node_express` (15 pts)** — the two core stack
  requirements ("must have", not optional per the JD).
- **`sql_nosql` (10 pts)**, **`fullstack` (10 pts)** — secondary must-have signals.
- **`build_tooling`, `testing`, `devops_basics` (5 pts each)** — the JD's "nice to have"
  list (Vite, Jest/RTL, Docker/CI). Deliberately excludes webpack — the JD explicitly
  says "webpack experience doesn't transfer."
- **`git` (3 pts)** — baseline expectation, low weight since assumed universal.
- **No location bonus** — candidates are sourced from anywhere, not just
  Gurugram/Delhi NCR.
- **Experience-band bonus** — +5 if the headline mentions phrasing consistent with
  1-3 years (e.g. "2 years", "3+ years").
- **Connection bonus** — +3 for 1st/2nd degree connections (warmer outreach path).

Unlike the HandyPanda founding-engineer script this one was adapted from, there is no
seniority bonus — "senior/staff/principal" in a headline signals a JD mismatch
(overqualified for a 1-3 YOE role), not a fit signal.

## Known limitations

- Scoring only sees search-card text (name/headline/location), not full profile
  content — misses candidates whose headline is generic even if their experience
  fits.
- Keyword match, not semantic — synonyms or unlisted stack terms score zero.
- Query list and `JD_SIGNALS` are hand-tuned to this specific JD; reusing this script
  for a different role requires rewriting both.
- `--min-years`/`--max-years` parse years-of-experience only from headline text via
  regex (e.g. "3+ yrs") — most LinkedIn headlines don't state this explicitly, so the
  filter mostly passes candidates through as "unknown" rather than excluding them.
