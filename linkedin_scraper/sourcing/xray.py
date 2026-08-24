"""Google X-ray query generation and result parsing for candidate discovery.

Generates site:linkedin.com/in/ boolean queries from JD signals, and parses
Serper.dev's raw SERP hits (title/link/snippet) back into PersonSearchResult
objects. Both halves are pure/network-free so they're independently testable.
"""

import logging
import re
from typing import Dict, List, Optional, Set

from ..models.jd_signals import JDSignals
from ..models.person_search import PersonSearchResult
from .serp_client import SerpResult

logger = logging.getLogger(__name__)

_DEFAULT_EXCLUSIONS = ("recruiter", "intern")

_LINKEDIN_SUFFIX_RE = re.compile(r"\s*\|\s*LinkedIn\s*$", re.I)
_NAME_HEADLINE_RE = re.compile(r"^\s*(?P<name>[^-–]+?)\s*[-–]\s*(?P<headline>.+)$")


def build_xray_queries(
    signals: JDSignals,
    reference_terms: Optional[Dict[str, List[str]]] = None,
    college_terms: Optional[List[str]] = None,
    max_queries: int = 20,
    max_title_clauses: int = 4,
    max_skill_clauses: int = 6,
) -> List[str]:
    """
    Generate site:linkedin.com/in/ X-ray queries from JD signals.

    Titles and skills are chunked (not bundled into one giant OR clause) to
    keep individual queries precise, then fanned out into multiple queries -
    every title is guaranteed to appear in at least one query, up to
    max_queries total. college_terms, like locations, is ANDed as an OR-group
    onto every query (e.g. education-requirement filtering), not chunked.
    """
    reference_terms = reference_terms or {}
    titles = _dedup(list(signals.titles) + list(reference_terms.get("titles", [])))
    skills = _dedup(
        list(signals.must_have_skills)
        + list(signals.nice_to_have_skills)
        + list(reference_terms.get("skills", []))
    )
    locations = _dedup(list(signals.locations))
    colleges = _dedup(list(college_terms or []))
    exclusions = _build_exclusions(signals)

    title_chunks = _chunk(titles, max_title_clauses) or [[]]
    skill_chunks = _chunk(skills, max_skill_clauses) or [[]]

    if not title_chunks[0] and not skill_chunks[0]:
        return []

    queries: List[str] = []
    skill_chunks_per_title = max(1, max_queries // len(title_chunks))

    for title_chunk in title_chunks:
        for skill_chunk in skill_chunks[:skill_chunks_per_title]:
            if len(queries) >= max_queries:
                break
            queries.append(_render_query(title_chunk, skill_chunk, locations, colleges, exclusions))
        if len(queries) >= max_queries:
            break

    remaining_skill_chunks = skill_chunks[skill_chunks_per_title:]
    for idx, skill_chunk in enumerate(remaining_skill_chunks):
        if len(queries) >= max_queries:
            break
        title_chunk = title_chunks[idx % len(title_chunks)]
        queries.append(_render_query(title_chunk, skill_chunk, locations, colleges, exclusions))

    return queries


def parse_xray_result(raw: SerpResult, search_query: str) -> Optional[PersonSearchResult]:
    """Parse a single Serper.dev hit into a PersonSearchResult, or None if unparseable."""
    if "linkedin.com/in/" not in raw.link:
        return None

    title = (raw.title or "").strip()
    if not title:
        return None

    # Google's LinkedIn result titles usually end with "| LinkedIn", but not
    # always - strip it first so a literal "|" inside the headline itself
    # (e.g. "Founding Engineer | Nextjs | Node.js") isn't mistaken for it.
    title = _LINKEDIN_SUFFIX_RE.sub("", title).strip()
    if not title:
        return None

    match = _NAME_HEADLINE_RE.match(title)
    if match:
        name = match.group("name").strip()
        headline = match.group("headline").strip() or None
    else:
        name = title
        headline = None

    if not name:
        return None

    location = _guess_location_from_snippet(raw.snippet) if raw.snippet else None

    try:
        return PersonSearchResult(
            name=name,
            linkedin_url=raw.link.split("?")[0].rstrip("/"),
            headline=headline,
            location=location,
            search_query=search_query,
        )
    except Exception as exc:
        logger.debug("Skipping unparseable x-ray result %r: %s", raw.link, exc)
        return None


def parse_xray_results(raw_results: List[SerpResult], search_query: str) -> List[PersonSearchResult]:
    """Parse a batch of Serper.dev hits, deduping by linkedin_url within the batch."""
    results: List[PersonSearchResult] = []
    seen: Set[str] = set()
    for raw in raw_results:
        parsed = parse_xray_result(raw, search_query)
        if parsed is None or parsed.linkedin_url in seen:
            continue
        seen.add(parsed.linkedin_url)
        results.append(parsed)
    return results


def _dedup(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        stripped = item.strip()
        key = stripped.lower()
        if stripped and key not in seen:
            seen.add(key)
            out.append(stripped)
    return out


def _chunk(items: List[str], size: int) -> List[List[str]]:
    if not items:
        return []
    return [items[i : i + size] for i in range(0, len(items), size)]


def _or_group(terms: List[str]) -> str:
    quoted = [f'"{t}"' if " " in t else t for t in terms]
    if len(quoted) == 1:
        return quoted[0]
    return "(" + " OR ".join(quoted) + ")"


def _build_exclusions(signals: JDSignals) -> List[str]:
    haystack = {
        t.lower()
        for t in signals.titles + signals.must_have_skills + signals.nice_to_have_skills
    }
    excluded_lower = {t.lower() for t in signals.excluded_terms}
    terms = list(signals.excluded_terms)
    for term in _DEFAULT_EXCLUSIONS:
        if term not in haystack and term not in excluded_lower:
            terms.append(term)
    return [f'-"{t}"' if " " in t else f"-{t}" for t in terms]


def _render_query(
    title_chunk: List[str],
    skill_chunk: List[str],
    locations: List[str],
    colleges: List[str],
    exclusions: List[str],
) -> str:
    parts = ["site:linkedin.com/in/"]
    if title_chunk:
        parts.append(_or_group(title_chunk))
    if skill_chunk:
        parts.append(_or_group(skill_chunk))
    if locations:
        parts.append(_or_group(locations))
    if colleges:
        parts.append(_or_group(colleges))
    parts.extend(exclusions)
    return " ".join(parts)


def _guess_location_from_snippet(snippet: str) -> Optional[str]:
    for segment in re.split(r"[·|]", snippet):
        segment = segment.strip()
        if not segment or any(ch.isdigit() for ch in segment):
            continue
        if "," in segment and len(segment) < 80:
            return segment
    return None
