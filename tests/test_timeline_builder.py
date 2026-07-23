"""Unit tests for evaluation.timeline_builder.build_career_timeline - fully
deterministic, no LLM/network calls."""

import pytest

from linkedin_scraper.evaluation.timeline_builder import build_career_timeline
from linkedin_scraper.models.person import Education, Experience, Person


def _experience(title, company, from_date, to_date, employment_type=None) -> Experience:
    return Experience(
        position_title=title,
        institution_name=company,
        from_date=from_date,
        to_date=to_date,
        employment_type=employment_type,
    )


def _education(degree, school, from_date, to_date) -> Education:
    return Education(institution_name=school, degree=degree, from_date=from_date, to_date=to_date)


@pytest.mark.unit
class TestKindClassification:
    def test_employment_type_maps_to_kind(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[_experience("Intern", "Acme", "2019", "2020", employment_type="Internship")],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[0].kind == "internship"

    def test_unmapped_or_missing_employment_type_is_unknown(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[_experience("Eng", "Acme", "2019", "2020")],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[0].kind == "unknown"

    def test_education_entries_always_kind_education(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            educations=[_education("B.Tech", "IIT Bombay", "2014", "2018")],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[0].kind == "education"
        assert timeline.entries[0].transition is None


@pytest.mark.unit
class TestTransitionClassification:
    def test_first_work_entry_is_first_role(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[_experience("Eng", "Acme", "2019", "2020")],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[0].transition == "first_role"
        assert timeline.entries[0].domain_changed is False

    def test_different_company_is_transition(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[
                _experience("Senior Eng", "Startup", "2020", "2022"),
                _experience("Eng", "Acme", "2018", "2020"),
            ],
        )
        timeline = build_career_timeline(person)
        # oldest -> newest: Acme (2018) then Startup (2020)
        assert timeline.entries[0].institution == "Acme"
        assert timeline.entries[1].institution == "Startup"
        assert timeline.entries[1].transition == "transition"
        assert timeline.entries[1].domain_changed is True

    def test_same_company_different_title_is_promotion(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[
                _experience("Senior Eng", "Acme", "2020", "2022"),
                _experience("Eng", "Acme", "2018", "2020"),
            ],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[1].transition == "promotion"
        assert timeline.entries[1].domain_changed is False

    def test_same_company_same_title_is_function_change(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[
                _experience("Eng", "Acme", "2020", "2022"),
                _experience("Eng", "Acme", "2018", "2020"),
            ],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[1].transition == "function_change"


@pytest.mark.unit
class TestChronologicalSort:
    def test_merges_and_sorts_experiences_and_educations(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[_experience("Eng", "Acme", "2020", "Present")],
            educations=[_education("B.Tech", "IIT Bombay", "2014", "2018")],
        )
        timeline = build_career_timeline(person)
        assert [e.kind for e in timeline.entries] == ["education", "unknown"]

    def test_handles_partial_and_present_dates(self):
        person = Person(
            linkedin_url="https://linkedin.com/in/janedoe",
            experiences=[
                _experience("Senior Eng", "CRED", "2022", "Present"),
                _experience("Eng", "Startup", "2019", "2022"),
            ],
        )
        timeline = build_career_timeline(person)
        assert timeline.entries[0].institution == "Startup"
        assert timeline.entries[1].institution == "CRED"
        assert timeline.total_years_experience >= 2
