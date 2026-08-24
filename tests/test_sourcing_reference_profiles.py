"""Unit tests for reference-profile similarity derivation."""

import pytest

from linkedin_scraper.models.person import Education, Experience, Person
from linkedin_scraper.sourcing.reference_profiles import (
    build_similarity_signals,
    derive_reference_signal,
)


def _person(name: str, title: str, company: str, school: str, skills) -> Person:
    return Person(
        linkedin_url=f"https://www.linkedin.com/in/{name}",
        name=name,
        experiences=[Experience(position_title=title, institution_name=company)],
        educations=[Education(institution_name=school)],
        skills=skills,
    )


@pytest.mark.unit
class TestDeriveReferenceSignal:
    def test_ranks_common_titles_and_companies_by_frequency(self):
        people = [
            _person("a", "Founding Engineer", "Acme", "IIT Delhi", ["Rust", "Python"]),
            _person("b", "Founding Engineer", "Acme", "BITS Pilani", ["Rust", "Go"]),
            _person("c", "Backend Engineer", "Other Co", "IIT Bombay", ["Python"]),
        ]
        signal = derive_reference_signal(people)

        assert signal.titles[0] == "Founding Engineer"
        assert signal.companies[0] == "Acme"
        assert "Rust" in signal.skills
        assert "Python" in signal.skills
        assert len(signal.schools) == 3

    def test_empty_input_yields_empty_signal(self):
        signal = derive_reference_signal([])
        assert signal.titles == []
        assert signal.skills == []
        assert signal.companies == []
        assert signal.schools == []


@pytest.mark.unit
class TestBuildSimilaritySignals:
    def test_produces_weighted_groups_for_present_fields(self):
        people = [_person("a", "Founding Engineer", "Acme", "IIT Delhi", ["Rust"])]
        signal = derive_reference_signal(people)
        signals = build_similarity_signals(signal)

        assert "similar_company" in signals
        assert "similar_title" in signals
        weight, terms = signals["similar_company"]
        assert weight > 0
        assert "Acme" in terms

    def test_no_bonus_groups_when_signal_is_empty(self):
        from linkedin_scraper.sourcing.reference_profiles import ReferenceSignal

        signals = build_similarity_signals(ReferenceSignal())
        assert signals == {}
