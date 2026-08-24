"""Unit tests for JD-fit scoring."""

import pytest

from linkedin_scraper.models.jd_signals import JDSignals
from linkedin_scraper.models.person_search import PersonSearchResult
from linkedin_scraper.sourcing.scoring import (
    DEFAULT_JD_SIGNALS,
    rank_candidates,
    score_candidate_for_jd,
    signals_from_jd,
)


@pytest.mark.unit
def test_scores_founding_typescript_in_gurgaon():
    candidate = PersonSearchResult(
        name="Jane Doe",
        linkedin_url="https://www.linkedin.com/in/jane-doe",
        headline="Founding Engineer | TypeScript, React, AWS",
        location="Gurgaon, Haryana, India",
        connection_degree="2nd",
    )
    scored = score_candidate_for_jd(candidate, DEFAULT_JD_SIGNALS)

    assert scored.fit_score >= 50
    assert "founding early" in scored.fit_indicators
    assert "typescript node" in scored.fit_indicators
    assert "delhi ncr location" in scored.fit_indicators


@pytest.mark.unit
def test_rank_candidates_orders_by_score():
    low = PersonSearchResult(
        name="Low Fit",
        linkedin_url="https://www.linkedin.com/in/low-fit",
        headline="Recruiter",
        location="Mumbai",
    )
    high = PersonSearchResult(
        name="High Fit",
        linkedin_url="https://www.linkedin.com/in/high-fit",
        headline="Founding Engineer TypeScript AWS React",
        location="Gurgaon",
    )

    ranked = rank_candidates([low, high], DEFAULT_JD_SIGNALS)
    assert ranked[0].name == "High Fit"
    assert ranked[0].fit_score > ranked[1].fit_score


@pytest.mark.unit
def test_score_candidate_for_jd_with_custom_signals():
    signals = {"rust_backend": (30, ["rust", "actix"])}
    candidate = PersonSearchResult(
        name="Rust Dev",
        linkedin_url="https://www.linkedin.com/in/rust-dev",
        headline="Backend Engineer, Rust and Actix",
    )
    scored = score_candidate_for_jd(candidate, signals)
    assert scored.fit_score == 30
    assert "rust backend" in scored.fit_indicators


@pytest.mark.unit
def test_signals_from_jd_weights_must_have_above_nice_to_have():
    jd = JDSignals(
        titles=["Backend Engineer"],
        must_have_skills=["Python"],
        nice_to_have_skills=["Go"],
    )
    signals = signals_from_jd(jd)
    must_have_weight = signals["must_have_skills"][0]
    nice_to_have_weight = signals["nice_to_have_skills"][0]
    assert must_have_weight > nice_to_have_weight


@pytest.mark.unit
def test_yoe_range_scoring():
    candidate_in_range = PersonSearchResult(
        name="In Range",
        linkedin_url="https://www.linkedin.com/in/in-range",
        headline="Backend Engineer with 4 years experience",
    )
    candidate_out_of_range = PersonSearchResult(
        name="Out Of Range",
        linkedin_url="https://www.linkedin.com/in/out-of-range",
        headline="Backend Engineer with 1 years experience",
    )

    scored_in = score_candidate_for_jd(candidate_in_range, {}, yoe_range=(3, 6))
    scored_out = score_candidate_for_jd(candidate_out_of_range, {}, yoe_range=(3, 6))

    assert "yoe in range" in scored_in.fit_indicators
    assert "yoe in range" not in scored_out.fit_indicators
    assert scored_in.fit_score > scored_out.fit_score
