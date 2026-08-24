"""Candidate sourcing helpers."""

from .jd_parser import extract_jd_signals, jd_signals_from_flags
from .pipeline import (
    EnrichedCandidate,
    PipelineError,
    SessionRequiredError,
    SignalResolutionError,
    XraySearchOutcome,
    XraySearchParams,
    run_xray_search,
)
from .reference_profiles import (
    ReferenceSignal,
    build_similarity_signals,
    derive_reference_signal,
    load_or_scrape_reference_profiles,
)
from .scoring import (
    DEFAULT_JD_SIGNALS,
    passes_years_filter,
    rank_candidates,
    score_candidate_for_jd,
    signals_from_jd,
)
from .serp_client import SerperClient, SerpResult, SerpSearchError
from .skills import SkillEntry, aggregate_skills
from .xray import build_xray_queries, parse_xray_result, parse_xray_results

__all__ = [
    "extract_jd_signals",
    "jd_signals_from_flags",
    "score_candidate_for_jd",
    "rank_candidates",
    "signals_from_jd",
    "passes_years_filter",
    "DEFAULT_JD_SIGNALS",
    "SkillEntry",
    "aggregate_skills",
    "SerperClient",
    "SerpResult",
    "SerpSearchError",
    "build_xray_queries",
    "parse_xray_result",
    "parse_xray_results",
    "ReferenceSignal",
    "derive_reference_signal",
    "build_similarity_signals",
    "load_or_scrape_reference_profiles",
    "run_xray_search",
    "XraySearchParams",
    "XraySearchOutcome",
    "EnrichedCandidate",
    "PipelineError",
    "SignalResolutionError",
    "SessionRequiredError",
]
