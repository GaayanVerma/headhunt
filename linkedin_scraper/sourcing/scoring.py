"""JD-fit scoring for LinkedIn people search results.

score_candidate_for_jd/rank_candidates take a weighted keyword-group `signals`
dict as a required parameter rather than assuming one hardcoded JD - this is
the disclosed-formula scorer other layers (reference-profile similarity,
LLM-extracted JD signals) feed into. DEFAULT_JD_SIGNALS etc. below are kept
only as a concrete example/test fixture, not an implicit default.
"""

import re
from typing import Dict, List, Optional, Tuple

from ..models.jd_signals import JDSignals
from ..models.person_search import PersonSearchResult

# Example weighted keyword groups (originally the HandyPanda founding
# engineer role) - a concrete signals dict shape for tests/reference, not
# meant to be relied on as an implicit default for real searches.
DEFAULT_JD_SIGNALS: Dict[str, Tuple[int, List[str]]] = {
    "typescript_node": (
        15,
        ["typescript", "type script", "node.js", "nodejs", "node ", "trpc"],
    ),
    "react_fullstack": (
        12,
        ["react", "next.js", "nextjs", "full stack", "fullstack", "full-stack"],
    ),
    "aws_infra": (
        15,
        ["aws", "amazon web services", "ecs", "eks", "cloud infrastructure", "devops", "sre", "platform engineer"],
    ),
    "founding_early": (
        20,
        ["founding engineer", "founding", "first engineer", "employee #", "early engineer", "founder engineer"],
    ),
    "mobile": (8, ["react native", "expo", "mobile engineer", "mobile developer"]),
    "postgres_backend": (8, ["postgres", "postgresql", "prisma", "backend engineer", "backend developer"]),
    "startup": (10, ["startup", "early stage", "seed stage", "series a", "0 to 1", "0-1"]),
    "ai_llm": (6, ["llm", "genai", "generative ai", "ai engineer", "machine learning"]),
}

DELHI_NCR_LOCATIONS = [
    "gurgaon",
    "gurugram",
    "delhi",
    "noida",
    "faridabad",
    "ghaziabad",
    "delhi ncr",
    "national capital region",
    "haryana",
]

BANGALORE_LOCATIONS = ["bengaluru", "bangalore", "karnataka"]

SENIORITY_POSITIVE = [
    "senior",
    "staff",
    "lead",
    "principal",
    "architect",
    "3+",
    "4+",
    "5+",
]

_YEARS_PATTERN = re.compile(r"(\d{1,2})\s*\+?\s*(?:yrs?|years?|yoe)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def score_candidate_for_jd(
    candidate: PersonSearchResult,
    signals: Dict[str, Tuple[int, List[str]]],
    *,
    location_terms: Optional[Dict[str, int]] = None,
    seniority_terms: Optional[List[str]] = None,
    yoe_range: Optional[Tuple[Optional[int], Optional[int]]] = None,
) -> PersonSearchResult:
    """
    Score a search result against a weighted keyword-group signals dict.

    Mutates and returns the candidate with fit_score and fit_indicators set.
    location_terms maps a lowercase location substring to a score bonus
    (first match wins, checked in dict order); when omitted, falls back to
    the original Delhi-NCR/Bangalore weighting for behavioral compatibility.
    seniority_terms defaults to SENIORITY_POSITIVE; yoe_range=(min_years,
    max_years) gives a bonus when a "N years"/"N yoe" mention in the headline
    falls within range (either bound may be None).
    """
    seniority_terms = seniority_terms if seniority_terms is not None else SENIORITY_POSITIVE

    haystack = _normalize(
        " ".join(
            part
            for part in (candidate.name, candidate.headline, candidate.location)
            if part
        )
    )

    score = 0
    indicators: List[str] = []

    for label, (weight, keywords) in signals.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            score += weight
            indicators.append(label.replace("_", " "))

    if location_terms is not None:
        for loc, bonus in location_terms.items():
            if loc.lower() in haystack:
                score += bonus
                indicators.append(f"{loc} location")
                break
    else:
        if any(loc in haystack for loc in DELHI_NCR_LOCATIONS):
            score += 25
            indicators.append("delhi ncr location")
        elif any(loc in haystack for loc in BANGALORE_LOCATIONS):
            score += 8
            indicators.append("bangalore (relocate?)")

    if any(term in haystack for term in seniority_terms):
        score += 5
        indicators.append("seniority signal")

    if yoe_range is not None:
        min_years, max_years = yoe_range
        found = _extract_max_years(candidate.headline or "")
        if found is not None:
            if (min_years is None or found >= min_years) and (max_years is None or found <= max_years):
                score += 5
                indicators.append("yoe in range")

    if candidate.connection_degree in {"1st", "2nd"}:
        score += 3
        indicators.append(f"{candidate.connection_degree} connection")

    candidate.fit_score = score
    candidate.fit_indicators = indicators
    return candidate


def rank_candidates(
    candidates: List[PersonSearchResult],
    signals: Dict[str, Tuple[int, List[str]]],
    **scoring_kwargs,
) -> List[PersonSearchResult]:
    """Score and sort candidates by fit (descending), then name."""
    scored = [score_candidate_for_jd(candidate, signals, **scoring_kwargs) for candidate in candidates]
    return sorted(scored, key=lambda c: (-c.fit_score, c.name.lower()))


def signals_from_jd(jd: JDSignals) -> Dict[str, Tuple[int, List[str]]]:
    """
    Convert a JDSignals object into the weighted keyword-group dict shape
    score_candidate_for_jd expects.

    Must-have skills are weighted higher than nice-to-have; titles and
    company-stage get their own groups. This is the deterministic seam
    between LLM-extracted (or manually-flagged) JD signals and the
    disclosed-formula scorer - LLM output never touches score math directly,
    it only produces input to this mapping.
    """
    signals: Dict[str, Tuple[int, List[str]]] = {}
    if jd.titles:
        signals["title_match"] = (15, list(jd.titles))
    if jd.must_have_skills:
        signals["must_have_skills"] = (15, list(jd.must_have_skills))
    if jd.nice_to_have_skills:
        signals["nice_to_have_skills"] = (5, list(jd.nice_to_have_skills))
    if jd.company_stage:
        signals["company_stage"] = (8, [jd.company_stage])
    return signals


def _extract_max_years(text: str) -> Optional[int]:
    """Pull the largest years-of-experience number mentioned in text, if any."""
    matches = [int(m) for m in _YEARS_PATTERN.findall(text or "")]
    return max(matches) if matches else None


def passes_years_filter(
    candidate: PersonSearchResult,
    min_years: Optional[int],
    max_years: Optional[int],
) -> bool:
    """
    Keep candidates whose stated YOE (if any) falls within [min_years, max_years].

    Search cards don't always state years of experience explicitly, so
    candidates with no YOE mention are kept (unknown, not excluded) rather
    than dropped outright.
    """
    if min_years is None and max_years is None:
        return True
    found = _extract_max_years(candidate.headline or "")
    if found is None:
        return True
    if max_years is not None and found > max_years:
        return False
    if min_years is not None and found < min_years:
        return False
    return True
