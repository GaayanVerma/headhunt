"""JD-fit scoring for LinkedIn people search results."""

from typing import Dict, List, Tuple

from ..models.person_search import PersonSearchResult

# Weighted keyword groups for the HandyPanda founding engineer role.
JD_SIGNALS: Dict[str, Tuple[int, List[str]]] = {
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


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def score_candidate_for_jd(candidate: PersonSearchResult) -> PersonSearchResult:
    """
    Score a search result against the founding engineer JD.

    Mutates and returns the candidate with fit_score and fit_indicators set.
    """
    haystack = _normalize(
        " ".join(
            part
            for part in (candidate.name, candidate.headline, candidate.location)
            if part
        )
    )

    score = 0
    indicators: List[str] = []

    for label, (weight, keywords) in JD_SIGNALS.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            score += weight
            indicators.append(label.replace("_", " "))

    if any(loc in haystack for loc in DELHI_NCR_LOCATIONS):
        score += 25
        indicators.append("delhi ncr location")
    elif any(loc in haystack for loc in BANGALORE_LOCATIONS):
        score += 8
        indicators.append("bangalore (relocate?)")

    if any(term in haystack for term in SENIORITY_POSITIVE):
        score += 5
        indicators.append("seniority signal")

    if candidate.connection_degree in {"1st", "2nd"}:
        score += 3
        indicators.append(f"{candidate.connection_degree} connection")

    candidate.fit_score = score
    candidate.fit_indicators = indicators
    return candidate


def rank_candidates(candidates: List[PersonSearchResult]) -> List[PersonSearchResult]:
    """Score and sort candidates by fit (descending), then name."""
    scored = [score_candidate_for_jd(candidate) for candidate in candidates]
    return sorted(scored, key=lambda c: (-c.fit_score, c.name.lower()))
