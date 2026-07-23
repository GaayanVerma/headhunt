"""Unit tests for the extract -> headhunt-G adapter - no network/LLM calls."""

import pytest

from linkedin_scraper.evaluation.timeline_builder import build_career_timeline
from linkedin_scraper.export.headhunt_adapter import (
    build_headhunt_payload,
    map_candidate_profile,
    map_education,
    map_evaluation_result,
    map_experiences,
    map_external_sources,
    map_projects_from_github,
    map_raw_text,
    map_skill_groups,
)
from linkedin_scraper.models.github import (
    AggregateFeatures,
    GitHubAnalysisResult,
    GitHubCandidateSummary,
    LanguageRollup,
    ParserMetadata,
    Repository,
    SourceMetadata,
)
from linkedin_scraper.models.person import Education, Experience, Person
from linkedin_scraper.models.readiness import (
    OverallReadinessAssessment,
    ReadinessDimensionAssessment,
    ReadinessDimensions,
    StartupReadinessEvaluation,
)
from linkedin_scraper.models.resume import ResumeData


def _experience(title, company, from_date, to_date) -> Experience:
    return Experience(
        position_title=title,
        institution_name=company,
        from_date=from_date,
        to_date=to_date,
        description="did stuff",
    )


def _evaluation(**overrides) -> StartupReadinessEvaluation:
    dim = ReadinessDimensionAssessment(assessment="a", confidence="MEDIUM", score=60, evidence_basis=["e"])
    defaults = dict(
        candidate_id="cand-1",
        overall_readiness_assessment=OverallReadinessAssessment(summary="s", confidence="MEDIUM"),
        overall_score=74,
        recommendation="possible_match",
        dimensions=ReadinessDimensions(
            ownership_and_proactivity=dim,
            execution_credibility=dim,
            drive_and_ambition=dim,
            adaptability=dim,
        ),
        founder_takeaway="takeaway",
    )
    defaults.update(overrides)
    return StartupReadinessEvaluation(**defaults)


def _repo(name, stars=0, is_fork=False, language="Go") -> Repository:
    return Repository(
        id=name,
        name=name,
        full_name=f"janedoe/{name}",
        url=f"https://github.com/janedoe/{name}",
        owner_login="janedoe",
        owner_type="USER",
        is_fork=is_fork,
        stars=stars,
        primary_language=language,
        description=f"{name} description",
    )


def _github_result(repos, top_languages=None) -> GitHubAnalysisResult:
    from datetime import datetime, timezone

    return GitHubAnalysisResult(
        source_metadata=SourceMetadata(input_url_raw="https://github.com/janedoe", fetched_at=datetime.now(timezone.utc)),
        parser_metadata=ParserMetadata(analyzer_version="1"),
        repositories=repos,
        aggregate_features=AggregateFeatures(
            top_languages=[LanguageRollup(language=lang, repo_count=1, total_bytes=100) for lang in (top_languages or [])]
        ),
    )


@pytest.mark.unit
def test_map_experiences_renames_dates_and_orders_chronologically():
    person = Person(
        linkedin_url="https://linkedin.com/in/janedoe",
        experiences=[
            _experience("Senior Eng", "CRED", "2022", "Present"),
            _experience("Eng", "Startup", "2019", "2022"),
        ],
    )
    mapped = map_experiences(build_career_timeline(person))
    assert mapped[0]["title"] == "Eng"
    assert mapped[0]["startDate"] == "2019"
    assert mapped[0]["endDate"] == "2022"
    assert "tag" not in mapped[0]
    assert mapped[1]["title"] == "Senior Eng"
    assert "endDate" not in mapped[1]
    assert mapped[1]["tag"] == {"kind": "transition", "label": "Stage transition"}
    assert mapped[1]["context"] == "Domain change"


@pytest.mark.unit
def test_map_education_orders_chronologically():
    person = Person(
        linkedin_url="https://linkedin.com/in/janedoe",
        educations=[
            Education(institution_name="IIT Bombay", degree="M.Tech", from_date="2018", to_date="2020"),
            Education(institution_name="School", degree="High School", from_date="2010", to_date="2014"),
        ],
    )
    mapped = map_education(build_career_timeline(person))
    assert mapped[0]["school"] == "School"
    assert mapped[1]["school"] == "IIT Bombay"


@pytest.mark.unit
def test_map_projects_from_github_excludes_forks_and_sorts_by_stars():
    repos = [_repo("low", stars=1), _repo("high", stars=100), _repo("forked", stars=1000, is_fork=True)]
    projects = map_projects_from_github(_github_result(repos))
    assert [p["name"] for p in projects] == ["high", "low"]
    assert all(p["sourceType"] == "github_repo" for p in projects)
    assert all(p["kind"] == "GitHub" for p in projects)


@pytest.mark.unit
def test_map_projects_from_github_handles_none():
    assert map_projects_from_github(None) == []


@pytest.mark.unit
def test_map_external_sources_dedupes_and_tags_source():
    person = Person(linkedin_url="https://linkedin.com/in/janedoe", name="Jane")
    resume = ResumeData(
        github_url="https://github.com/janedoe",
        linkedin_url="https://linkedin.com/in/janedoe/",
        other_urls=["https://medium.com/@janedoe"],
    )
    sources = map_external_sources(person, resume)
    hrefs = [s["href"] for s in sources]
    assert hrefs.count("https://linkedin.com/in/janedoe") + hrefs.count("https://linkedin.com/in/janedoe/") == 1
    categories = {s["category"] for s in sources}
    assert categories == {"GitHub", "LinkedIn", "Medium"}
    assert all(s["sourceType"] == "resume_link" for s in sources)


@pytest.mark.unit
def test_map_raw_text_prefers_resume_then_falls_back_to_person():
    resume = ResumeData(raw_text="full resume text")
    assert map_raw_text(None, resume) == "full resume text"

    person = Person(linkedin_url="https://linkedin.com/in/janedoe", about="Backend engineer.")
    empty_resume = ResumeData(raw_text="")
    text = map_raw_text(person, empty_resume)
    assert "Backend engineer." in text


@pytest.mark.unit
def test_map_raw_text_raises_when_nothing_available():
    with pytest.raises(ValueError):
        map_raw_text(None, ResumeData(raw_text=""))


@pytest.mark.unit
def test_map_evaluation_result_renames_dimensions():
    evaluation = _evaluation()
    result = map_evaluation_result(evaluation)
    assert result["overallScore"] == 74
    assert result["recommendation"] == "possible_match"
    dims = {r["dimension"] for r in result["readiness"]}
    assert dims == {"ownership", "execution", "ambition", "learnability"}
    assert len(result["readiness"]) == 4


@pytest.mark.unit
def test_map_candidate_profile_skill_groups_empty_without_github():
    profile = map_candidate_profile(None, None, None)
    assert profile["skillGroups"] == []
    assert profile["experiences"] == []
    assert profile["projects"] == []
    assert profile["externalSources"] == []


@pytest.mark.unit
def test_map_skill_groups_derived_from_github_top_technologies():
    github_summary = GitHubCandidateSummary(top_technologies=["Go", "Python"])
    groups = map_skill_groups(github_summary)
    assert groups == [{"label": "Technologies (GitHub)", "skills": ["Go", "Python"]}]


@pytest.mark.unit
def test_map_skill_groups_empty_when_no_signal():
    assert map_skill_groups(None) == []
    assert map_skill_groups(GitHubCandidateSummary(top_technologies=[])) == []


@pytest.mark.unit
def test_map_skill_groups_includes_resume_skills():
    resume = ResumeData(skills=["Python", "Kubernetes"])
    groups = map_skill_groups(None, resume)
    assert groups == [{"label": "Skills (Resume)", "skills": ["Python", "Kubernetes"]}]


@pytest.mark.unit
def test_map_skill_groups_combines_resume_and_github_sources():
    resume = ResumeData(skills=["Python"])
    github_summary = GitHubCandidateSummary(top_technologies=["Go"])
    groups = map_skill_groups(github_summary, resume)
    labels = {g["label"] for g in groups}
    assert labels == {"Skills (Resume)", "Technologies (GitHub)"}


@pytest.mark.unit
def test_compute_total_years_experience_via_candidate_profile():
    person = Person(
        linkedin_url="https://linkedin.com/in/janedoe",
        name="Jane",
        experiences=[
            _experience("Senior Eng", "CRED", "2022", "Present"),
            _experience("Eng", "Startup", "2019", "2022"),
        ],
    )
    profile = map_candidate_profile(person, None, None)
    current_year_span = profile["totalYearsExperience"]
    assert current_year_span >= 2  # 2019 -> current year, at minimum 2019-2022


@pytest.mark.unit
def test_total_years_experience_none_without_person():
    profile = map_candidate_profile(None, None, None)
    assert "totalYearsExperience" not in profile


@pytest.mark.unit
def test_build_headhunt_payload_full_contract():
    person = Person(
        linkedin_url="https://linkedin.com/in/janedoe",
        name="Jane Doe",
        location="Bangalore, India",
        about="Backend engineer.",
        experiences=[_experience("Senior Eng", "CRED", "2022", "Present")],
        educations=[Education(institution_name="IIT Bombay", degree="B.Tech", from_date="2014", to_date="2018")],
    )
    resume = ResumeData(raw_text="resume text", github_url="https://github.com/janedoe")
    github_result = _github_result([_repo("distributed-cache", stars=50)])
    evaluation = _evaluation()

    payload = build_headhunt_payload(person, resume, github_result, evaluation, model="claude-opus-4-8")

    assert set(payload.keys()) == {"candidateProfile", "evaluationResult", "model", "rawText"}
    assert payload["candidateProfile"]["name"] == "Jane Doe"
    assert payload["candidateProfile"]["projects"][0]["sourceType"] == "github_repo"
    assert payload["evaluationResult"]["overallScore"] == 74
    assert payload["rawText"] == "resume text"
    assert payload["model"] == "claude-opus-4-8"
    assert "narrative" not in payload["candidateProfile"]


@pytest.mark.unit
def test_build_headhunt_payload_fills_narrative_from_evaluation():
    evaluation = _evaluation(candidate_narrative="Backend engineer who ships fast.")
    payload = build_headhunt_payload(None, ResumeData(raw_text="text"), None, evaluation, model="m")
    assert payload["candidateProfile"]["narrative"] == "Backend engineer who ships fast."
