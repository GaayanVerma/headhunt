"""Unit tests for X-ray query generation and SERP result parsing."""

import pytest

from linkedin_scraper.models.jd_signals import JDSignals
from linkedin_scraper.sourcing.serp_client import SerpResult
from linkedin_scraper.sourcing.xray import (
    build_xray_queries,
    parse_xray_result,
    parse_xray_results,
)


@pytest.mark.unit
class TestBuildXrayQueries:
    def test_basic_query_shape(self):
        signals = JDSignals(
            titles=["Senior Backend Engineer", "Staff Engineer"],
            must_have_skills=["Python", "Django", "FastAPI"],
            locations=["Bangalore"],
        )
        queries = build_xray_queries(signals)

        assert queries
        for query in queries:
            assert query.startswith("site:linkedin.com/in/")
            assert "-recruiter" in query
            assert "-intern" in query

        joined = " ".join(queries)
        assert '"Senior Backend Engineer"' in joined
        assert '"Staff Engineer"' in joined
        assert "Python" in joined
        assert "Bangalore" in joined

    def test_excludes_are_not_duplicated_when_jd_wants_interns(self):
        signals = JDSignals(titles=["Intern"], excluded_terms=["recruiter"])
        queries = build_xray_queries(signals)
        joined = " ".join(queries)
        assert "-intern" not in joined
        assert joined.count("-recruiter") == len(queries)

    def test_max_queries_cap_with_full_title_coverage(self):
        titles = [f"Engineer Level {i}" for i in range(10)]
        signals = JDSignals(titles=titles)
        queries = build_xray_queries(signals, max_queries=20, max_title_clauses=4)

        assert len(queries) <= 20
        joined = " ".join(queries)
        for title in titles:
            assert f'"{title}"' in joined

    def test_no_signals_returns_empty(self):
        assert build_xray_queries(JDSignals()) == []

    def test_college_terms_anded_onto_every_query(self):
        signals = JDSignals(titles=["Founding Engineer", "Backend Engineer"], locations=["Bangalore"])
        queries = build_xray_queries(
            signals, college_terms=["IIT", "NIT", "BITS"], max_title_clauses=1, max_queries=10
        )
        assert len(queries) >= 2
        for query in queries:
            assert "(IIT OR NIT OR BITS)" in query

    def test_reference_terms_merged_in(self):
        signals = JDSignals(titles=["Founding Engineer"])
        queries = build_xray_queries(
            signals, reference_terms={"titles": ["Staff Engineer"], "skills": ["Rust"]}
        )
        joined = " ".join(queries)
        assert '"Founding Engineer"' in joined
        assert '"Staff Engineer"' in joined
        assert "Rust" in joined


@pytest.mark.unit
class TestParseXrayResult:
    def test_parses_standard_title_format(self):
        raw = SerpResult(
            title="Jane Doe - Senior Backend Engineer at Acme | LinkedIn",
            link="https://www.linkedin.com/in/jane-doe/",
            snippet="Bangalore, Karnataka, India · 500+ connections",
        )
        result = parse_xray_result(raw, "some query")
        assert result is not None
        assert result.name == "Jane Doe"
        assert result.headline == "Senior Backend Engineer at Acme"
        assert result.location == "Bangalore, Karnataka, India"
        assert result.search_query == "some query"

    def test_parses_title_missing_headline_segment(self):
        raw = SerpResult(title="Jane Doe | LinkedIn", link="https://www.linkedin.com/in/jane-doe/")
        result = parse_xray_result(raw, "q")
        assert result is not None
        assert result.name == "Jane Doe"
        assert result.headline is None

    def test_rejects_non_profile_link(self):
        raw = SerpResult(
            title="Acme Corp | LinkedIn",
            link="https://www.linkedin.com/company/acme/",
        )
        assert parse_xray_result(raw, "q") is None

    def test_rejects_empty_title(self):
        raw = SerpResult(title="", link="https://www.linkedin.com/in/jane-doe/")
        assert parse_xray_result(raw, "q") is None

    def test_parses_title_without_linkedin_suffix_and_pipes_in_headline(self):
        # Real Serper.dev output doesn't always carry "| LinkedIn", and
        # headlines commonly use "|" as their own delimiter.
        raw = SerpResult(
            title="Ankit Ahirwar - Founding Engineer | Nextjs | Node.js | Java",
            link="https://in.linkedin.com/in/ankitahirwar",
        )
        result = parse_xray_result(raw, "q")
        assert result is not None
        assert result.name == "Ankit Ahirwar"
        assert result.headline == "Founding Engineer | Nextjs | Node.js | Java"

    def test_malformed_title_falls_back_to_whole_string_as_name(self):
        raw = SerpResult(title="Just A Name", link="https://www.linkedin.com/in/jane-doe/")
        result = parse_xray_result(raw, "q")
        assert result is not None
        assert result.name == "Just A Name"
        assert result.headline is None


@pytest.mark.unit
class TestParseXrayResults:
    def test_dedupes_within_batch(self):
        raw = [
            SerpResult(title="Jane Doe - Engineer | LinkedIn", link="https://www.linkedin.com/in/jane-doe/"),
            SerpResult(title="Jane Doe - Engineer | LinkedIn", link="https://www.linkedin.com/in/jane-doe"),
        ]
        results = parse_xray_results(raw, "q")
        assert len(results) == 1

    def test_skips_unparseable_without_raising(self):
        raw = [
            SerpResult(title="Acme | LinkedIn", link="https://www.linkedin.com/company/acme/"),
            SerpResult(title="Jane Doe - Engineer | LinkedIn", link="https://www.linkedin.com/in/jane-doe/"),
        ]
        results = parse_xray_results(raw, "q")
        assert len(results) == 1
        assert results[0].name == "Jane Doe"
