"""Unit tests for JD-fit scoring."""

import pytest

from linkedin_scraper.models.person_search import PersonSearchResult
from linkedin_scraper.sourcing.scoring import rank_candidates, score_candidate_for_jd


@pytest.mark.unit
def test_scores_founding_typescript_in_gurgaon():
    candidate = PersonSearchResult(
        name="Jane Doe",
        linkedin_url="https://www.linkedin.com/in/jane-doe",
        headline="Founding Engineer | TypeScript, React, AWS",
        location="Gurgaon, Haryana, India",
        connection_degree="2nd",
    )
    scored = score_candidate_for_jd(candidate)

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

    ranked = rank_candidates([low, high])
    assert ranked[0].name == "High Fit"
    assert ranked[0].fit_score > ranked[1].fit_score
