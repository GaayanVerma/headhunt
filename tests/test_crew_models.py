"""Unit tests for crew models / review parsing (no CrewAI runtime required)."""

import pytest

from linkedin_scraper.crew.models import AuthorityReview, CandidateVerdict
from linkedin_scraper.crew.review import parse_authority_review


pytestmark = pytest.mark.unit


def test_candidate_verdict_defaults():
    verdict = CandidateVerdict(
        name="Ada Lovelace",
        linkedin_url="https://www.linkedin.com/in/ada",
        sources=["google", "linkedin"],
        decision="shortlist",
        rationale="Title + overlap across both sources",
    )
    assert verdict.fit_score == 0
    assert verdict.decision == "shortlist"


def test_parse_authority_review_from_json_blob():
    raw = """
    Here is my review:
    {
      "shortlist": [{
        "name": "Ada",
        "linkedin_url": "https://www.linkedin.com/in/ada",
        "sources": ["google"],
        "fit_score": 12,
        "decision": "shortlist",
        "rationale": "Strong TypeScript signal"
      }],
      "maybe": [],
      "rejected_count": 3,
      "linkedin_count": 2,
      "google_count": 5,
      "overlap_count": 1,
      "summary": "Google recall dominated; one overlap kept."
    }
    """
    review = parse_authority_review(raw)
    assert isinstance(review, AuthorityReview)
    assert review.rejected_count == 3
    assert review.shortlist[0].name == "Ada"
    assert "overlap" in review.summary.lower()


def test_parse_authority_review_fallback_on_garbage():
    review = parse_authority_review("not json at all")
    assert review.shortlist == []
    assert "not json" in review.summary
