"""Pydantic data models for LinkedIn scraper."""

from .person import Person, Experience, Education, Contact, Accomplishment, Interest
from .person_search import PersonSearchResult
from .jd_signals import JDSignals
from .company import Company, CompanySummary, Employee
from .job import Job
from .post import Post
from .resume import ResumeData, ResumeProject
from .github import (
    GitHubProfile,
    Repository,
    AggregateFeatures,
    FrameworkRollup,
    LLMSnapshot,
    Limitations,
    GitHubAnalysisResult,
    GitHubCandidateSummary,
    UnlistedProject,
)
from .timeline import CareerTimeline, TimelineEntry
from .contributions import (
    ContributedRepository,
    ContributionFacts,
    ContributionLimitations,
    DerivedContributionMetrics,
)
from .ai_insights import (
    EvidenceFileRef,
    CodeQualitySignals,
    RepoInsight,
    LLMRepoInsights,
    LLMRepoInsightsLimitations,
    CandidateLLMSnapshot,
    CandidateGitHubAIResult,
)
from .readiness import (
    ReadinessDimensionAssessment,
    ReadinessDimensions,
    OverallReadinessAssessment,
    StartupReadinessEvaluation,
)

__all__ = [
    "Person",
    "PersonSearchResult",
    "JDSignals",
    "Experience",
    "Education",
    "Contact",
    "Accomplishment",
    "Interest",
    "Company",
    "CompanySummary",
    "Employee",
    "Job",
    "Post",
    "ResumeData",
    "ResumeProject",
    "GitHubProfile",
    "Repository",
    "AggregateFeatures",
    "FrameworkRollup",
    "LLMSnapshot",
    "Limitations",
    "GitHubAnalysisResult",
    "GitHubCandidateSummary",
    "UnlistedProject",
    "CareerTimeline",
    "TimelineEntry",
    "ContributedRepository",
    "ContributionFacts",
    "ContributionLimitations",
    "DerivedContributionMetrics",
    "EvidenceFileRef",
    "CodeQualitySignals",
    "RepoInsight",
    "LLMRepoInsights",
    "LLMRepoInsightsLimitations",
    "CandidateLLMSnapshot",
    "CandidateGitHubAIResult",
    "ReadinessDimensionAssessment",
    "ReadinessDimensions",
    "OverallReadinessAssessment",
    "StartupReadinessEvaluation",
]
