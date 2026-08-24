"""Multi-agent candidate sourcing crew (CrewAI).

Architecture:
  LinkedIn Searcher  ──┐
                       ├──► Authority Reviewer (high bar) ──► shortlist JSON
  Google Searcher    ──┘

Optional dependency: pip install -e ".[crew]"
"""

from .models import AuthorityReview, CandidateVerdict
from .review import parse_authority_review

__all__ = [
    "AuthorityReview",
    "CandidateVerdict",
    "build_sourcing_crew",
    "parse_authority_review",
    "run_sourcing_crew",
]


def __getattr__(name: str):
    # Lazy: assembling/running a Crew requires the optional crewai extra.
    if name in {"build_sourcing_crew", "run_sourcing_crew"}:
        from . import crew as crew_module

        return getattr(crew_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
