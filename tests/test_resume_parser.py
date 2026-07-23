"""Unit tests for ResumeParser — uses real candidate PDFs in linkedin_scraper/candidates/."""

import os
import pytest
from pathlib import Path

from linkedin_scraper import ResumeParser, ResumeData
from linkedin_scraper.resume.parser import (
    _split_sections,
    _parse_skills_section,
    _parse_projects_section,
)

CANDIDATES_DIR = Path(__file__).parent.parent / "linkedin_scraper" / "candidates"

# Collect all PDFs under candidates/
CANDIDATE_PDFS = list(CANDIDATES_DIR.rglob("*.pdf"))


@pytest.mark.unit
class TestResumeParserBasic:
    def test_parser_instantiates(self):
        assert ResumeParser() is not None

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            ResumeParser().parse("/nonexistent/path/resume.pdf")

    def test_returns_resume_data_model(self):
        if not CANDIDATE_PDFS:
            pytest.skip("No candidate PDFs found")
        result = ResumeParser().parse(str(CANDIDATE_PDFS[0]))
        assert isinstance(result, ResumeData)

    def test_raw_text_populated(self):
        if not CANDIDATE_PDFS:
            pytest.skip("No candidate PDFs found")
        result = ResumeParser().parse(str(CANDIDATE_PDFS[0]))
        assert len(result.raw_text) > 50

    def test_links_is_list(self):
        if not CANDIDATE_PDFS:
            pytest.skip("No candidate PDFs found")
        result = ResumeParser().parse(str(CANDIDATE_PDFS[0]))
        assert isinstance(result.links, list)

    def test_other_urls_is_list(self):
        if not CANDIDATE_PDFS:
            pytest.skip("No candidate PDFs found")
        result = ResumeParser().parse(str(CANDIDATE_PDFS[0]))
        assert isinstance(result.other_urls, list)


@pytest.mark.unit
class TestSkillsAndProjectsSections:
    def test_skills_comma_separated(self):
        body = "Python, JavaScript, React, Docker"
        assert _parse_skills_section(body) == ["Python", "JavaScript", "React", "Docker"]

    def test_skills_bullet_separated(self):
        body = "• Python\n• JavaScript\n- React"
        assert _parse_skills_section(body) == ["Python", "JavaScript", "React"]

    def test_skills_dedupes_case_insensitively(self):
        body = "Python, python, PYTHON, Java"
        assert _parse_skills_section(body) == ["Python", "Java"]

    def test_split_sections_finds_skills_header(self):
        raw_text = "John Doe\n\nSkills\nPython, Go\n\nExperience\nDid stuff."
        sections = _split_sections(raw_text)
        assert sections["skills"] == "Python, Go"

    def test_split_sections_no_headers_found(self):
        assert _split_sections("Just some resume text with no headers.") == {}

    def test_projects_section_with_tech_label(self):
        body = "Portfolio Site\nBuilt a personal site.\nTech: React, Node.js\n\nCLI Tool\nA command line tool.\nStack: Python, Click"
        projects = _parse_projects_section(body)
        assert len(projects) == 2
        assert projects[0].name == "Portfolio Site"
        assert projects[0].technologies == ["React", "Node.js"]
        assert "Built a personal site" in projects[0].description
        assert projects[1].name == "CLI Tool"
        assert projects[1].technologies == ["Python", "Click"]

    def test_projects_section_no_reliable_titles_keeps_raw_block(self):
        body = "http://example.com/a-very-long-line-that-does-not-look-like-a-project-title-at-all-because-it-is-too-long-to-be-one"
        projects = _parse_projects_section(body)
        assert len(projects) == 1
        assert projects[0].name is None
        assert projects[0].description == body

    def test_empty_projects_section(self):
        assert _parse_projects_section("") == []

    def test_resume_data_has_skills_and_projects_defaults(self):
        data = ResumeData()
        assert data.skills == []
        assert data.projects == []


@pytest.mark.unit
@pytest.mark.parametrize("pdf_path", CANDIDATE_PDFS, ids=[p.parent.name for p in CANDIDATE_PDFS])
class TestAllCandidatePDFs:
    def test_parses_without_error(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        assert isinstance(result, ResumeData)

    def test_has_text(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        assert len(result.raw_text.strip()) > 0, f"No text extracted from {pdf_path.name}"

    def test_links_are_strings(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        for link in result.links:
            assert isinstance(link, str)
            assert link.startswith("http")

    def test_email_format(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        if result.email:
            assert "@" in result.email

    def test_linkedin_url_contains_linkedin(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        if result.linkedin_url:
            assert "linkedin.com" in result.linkedin_url.lower()

    def test_github_url_contains_github(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        if result.github_url:
            assert "github.com" in result.github_url.lower()

    def test_skills_is_list(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        assert isinstance(result.skills, list)

    def test_projects_is_list(self, pdf_path):
        result = ResumeParser().parse(str(pdf_path))
        assert isinstance(result.projects, list)

    def test_print_summary(self, pdf_path, capsys):
        """Print extracted info for manual review."""
        result = ResumeParser().parse(str(pdf_path))
        print(f"\n--- {pdf_path.parent.name} / {pdf_path.name} ---")
        print(f"  email:        {result.email}")
        print(f"  phone:        {result.phone}")
        print(f"  linkedin_url: {result.linkedin_url}")
        print(f"  github_url:   {result.github_url}")
        print(f"  other_urls:   {result.other_urls}")
        print(f"  all links:    {result.links}")
