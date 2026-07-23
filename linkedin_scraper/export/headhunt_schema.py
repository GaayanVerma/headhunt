"""Typed mirror of the headhunt-G Postgres schema (headhunt-dev Aurora cluster, `public` schema).

Pulled directly from information_schema.columns on 2026-07-12. This exists because
headhunt_adapter.py's payload dicts (candidateProfile / evaluationResult / ...) don't make
it obvious which fields the destination DB actually stores, which columns are NOT NULL,
or which are child tables keyed by candidate_id/evaluation_id. Keep this in sync if the
headhunt-G schema changes — it is not read/imported by the adapter, it's a reference.

Each dataclass documents one table. `nullable=False` fields are NOT NULL in Postgres:
omitting them (or sending None) will fail the insert on the headhunt-G side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Candidate:
    """Table: candidates — one row per candidate. Parent of all candidate_* child tables."""

    id: str  # uuid, default gen_random_uuid()
    org_id: str  # NOT NULL
    raw_text: str  # NOT NULL — full text blob used as evaluation source of truth
    created_at: datetime  # NOT NULL, default now()
    updated_at: datetime  # NOT NULL, default now()
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    summary: str | None = None
    narrative: str | None = None  # always null from extract today — no source field
    photo_url: str | None = None
    resume_filename: str | None = None
    resume_url: str | None = None
    resume_key: str | None = None
    total_years_experience: float | None = None  # always null from extract today — never computed


@dataclass
class CandidateExperience:
    """Table: candidate_experiences — child of candidates via candidate_id, ordered by sort_order."""

    id: str  # uuid
    candidate_id: str  # uuid, NOT NULL, FK -> candidates.id
    sort_order: int  # NOT NULL, default 0
    title: str  # NOT NULL
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    context: str | None = None  # always null from extract today
    tag_kind: str | None = None  # always null from extract today
    tag_label: str | None = None  # always null from extract today
    note: str | None = None  # always null from extract today


@dataclass
class CandidateEducation:
    """Table: candidate_education — child of candidates via candidate_id, ordered by sort_order."""

    id: str  # uuid
    candidate_id: str  # uuid, NOT NULL, FK -> candidates.id
    sort_order: int  # NOT NULL, default 0
    school: str  # NOT NULL
    degree: str | None = None
    field: str | None = None  # always null from extract today — no source field
    year: str | None = None


@dataclass
class CandidateSkillGroup:
    """Table: candidate_skill_groups — child of candidates via candidate_id, ordered by sort_order.

    THIS IS THE TABLE extract NEVER WRITES TO. headhunt_adapter.map_candidate_profile()
    hardcodes skillGroups=[] unconditionally (see headhunt_adapter.py), so no candidate
    exported through samples/export_to_headhunt.py gets a row here. Any populated
    skill_groups (e.g. Ada Okonkwo's "Programming Languages" / "Platforms" / "Domain
    Expertise") were entered directly in headhunt-G, not produced by this pipeline.
    """

    id: str  # uuid
    candidate_id: str  # uuid, NOT NULL, FK -> candidates.id
    sort_order: int  # NOT NULL, default 0
    label: str  # NOT NULL — group/category name, e.g. "Programming Languages"
    skills: list[str]  # NOT NULL, default '{}' — flat list of skill strings within the group


@dataclass
class CandidateProject:
    """Table: candidate_projects — child of candidates via candidate_id, ordered by sort_order.

    Populated by headhunt_adapter from the candidate's top 6 non-fork GitHub repos by
    stars — empty if no GitHubAnalysisResult was passed to build_headhunt_payload.
    """

    id: str  # uuid
    candidate_id: str  # uuid, NOT NULL, FK -> candidates.id
    sort_order: int  # NOT NULL, default 0
    name: str  # NOT NULL
    summary: str  # NOT NULL
    tech: list[str]  # NOT NULL, default '{}'
    kind: str | None = None
    href: str | None = None
    source_type: str | None = None


@dataclass
class CandidateExternalSource:
    """Table: candidate_external_sources — child of candidates via candidate_id, ordered by sort_order.

    Populated from deduped resume links + person.linkedin_url — empty if no resume and
    no LinkedIn URL was passed to build_headhunt_payload.
    """

    id: str  # uuid
    candidate_id: str  # uuid, NOT NULL, FK -> candidates.id
    sort_order: int  # NOT NULL, default 0
    category: str  # NOT NULL
    label: str  # NOT NULL
    href: str  # NOT NULL
    subtitle: str | None = None
    source_type: str | None = None


@dataclass
class Evaluation:
    """Table: evaluations — one row per (role, candidate) evaluation run."""

    id: str  # uuid
    org_id: str  # NOT NULL
    role_id: str  # uuid, NOT NULL, FK -> roles.id
    candidate_id: str  # uuid, NOT NULL, FK -> candidates.id
    overall_score: int  # NOT NULL
    recommendation: str  # NOT NULL
    model: str  # NOT NULL — e.g. LLM model id used to generate the evaluation
    created_at: datetime  # NOT NULL, default now()
    updated_at: datetime  # NOT NULL, default now()
    decision: str | None = None  # human decision, set later in headhunt-G's UI, not by extract


@dataclass
class EvaluationReadiness:
    """Table: evaluation_readiness — child of evaluations via evaluation_id, one row per dimension.

    extract's StartupReadinessEvaluation.dimensions (ownership/execution/ambition/
    learnability) map 1:1 to rows here.
    """

    id: str  # uuid
    evaluation_id: str  # uuid, NOT NULL, FK -> evaluations.id
    dimension: str  # NOT NULL
    score: int  # NOT NULL
    summary: str  # NOT NULL
    evidence: list[str]  # NOT NULL, default '{}'


@dataclass
class Role:
    """Table: roles — job requisition a candidate is evaluated against."""

    id: str  # uuid
    org_id: str  # NOT NULL
    title: str  # NOT NULL
    raw_jd: str  # NOT NULL
    must_have_skills: list[str]  # NOT NULL, default '{}'
    nice_to_have_skills: list[str]  # NOT NULL, default '{}'
    domains: list[str]  # NOT NULL, default '{}'
    responsibilities: list[str]  # NOT NULL, default '{}'
    created_at: datetime  # NOT NULL, default now()
    updated_at: datetime  # NOT NULL, default now()
    seniority: str | None = None
    min_years_experience: int | None = None
    location: str | None = None


# ---------------------------------------------------------------------------
# extract payload key -> headhunt-G table.column, for quick lookup when debugging
# a candidate missing data (e.g. "why does Kartik have no skills but Ada does").
# ---------------------------------------------------------------------------
PAYLOAD_FIELD_TO_TABLE_COLUMN: dict[str, str] = {
    "candidateProfile.name": "candidates.name",
    "candidateProfile.headline": "candidates.headline",
    "candidateProfile.location": "candidates.location",
    "candidateProfile.summary": "candidates.summary",
    "candidateProfile.narrative": "candidates.narrative",  # always null from extract
    "candidateProfile.totalYearsExperience": "candidates.total_years_experience",  # always null from extract
    "candidateProfile.experiences[]": "candidate_experiences.*",
    "candidateProfile.education[]": "candidate_education.*",
    "candidateProfile.skillGroups[]": "candidate_skill_groups.*",  # NEVER POPULATED by extract today
    "candidateProfile.projects[]": "candidate_projects.*",
    "candidateProfile.externalSources[]": "candidate_external_sources.*",
    "evaluationResult.overallScore": "evaluations.overall_score",
    "evaluationResult.recommendation": "evaluations.recommendation",
    "evaluationResult.readiness[]": "evaluation_readiness.*",
    "model": "evaluations.model",
    "rawText": "candidates.raw_text",
    "resumeFilename": "candidates.resume_filename",
}
