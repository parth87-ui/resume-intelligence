"""Pydantic request/response models.

These drive both validation and the auto-generated OpenAPI documentation at
``/docs``. Analysis payloads are returned as open dictionaries because their
shape is defined by the analysis service and documented in ``docs/API.md``;
everything the client sends is strictly validated.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

LevelId = Literal["intern", "entry", "mid", "senior"]


class HealthResponse(BaseModel):
    status: str
    version: str
    nlp_backend: dict[str, Any]
    similarity_method: str
    ai_engine: dict[str, Any]
    datasets: dict[str, int]


class CatalogCompany(BaseModel):
    id: str
    name: str
    tagline: str
    values: list[str]
    keywords: list[str]
    interview_focus: list[str] = []
    curated_roles: list[str] = []


class CatalogRole(BaseModel):
    id: str
    title: str
    family: str
    summary: str
    core_skills: list[str]


class CatalogLevel(BaseModel):
    id: str
    title: str
    expected_years: float
    expectations: list[str]
    weights: dict[str, float]


class CatalogSkill(BaseModel):
    name: str
    category: str
    category_label: str
    aliases: list[str]
    learn_weeks: int
    emerging: bool


class CatalogResponse(BaseModel):
    companies: list[CatalogCompany]
    roles: list[CatalogRole]
    levels: list[CatalogLevel]
    skill_count: int
    project_count: int
    scoring_weights: dict[str, float]


class UploadResponse(BaseModel):
    resume_id: int
    file_name: str
    contact: dict[str, str]
    sections_detected: list[str]
    skills_detected: list[str]
    skill_profile: dict[str, Any]
    metadata: dict[str, Any]
    warnings: list[str] = []
    parsed: dict[str, Any]


class AnalyseRequest(BaseModel):
    resume_id: int | None = Field(
        default=None, description="Id returned by /api/resume/upload."
    )
    resume_text: str | None = Field(
        default=None, description="Raw resume text, as an alternative to uploading a file."
    )
    company: str = Field(description="Company id, e.g. 'amazon'.")
    role: str = Field(description="Role id, e.g. 'machine-learning-engineer'.")
    level: LevelId = Field(default="entry", description="Target experience level.")
    persist: bool = Field(default=True, description="Store the analysis for later retrieval.")

    @field_validator("resume_text")
    @classmethod
    def _min_length(cls, value: str | None) -> str | None:
        if value is not None and len(value.split()) < 40:
            raise ValueError("resume_text is too short to analyse (minimum 40 words).")
        return value


class JobDescriptionRequest(BaseModel):
    resume_id: int | None = None
    resume_text: str | None = None
    job_description: str = Field(min_length=120, description="The full pasted job posting.")
    company_name: str = ""
    role_title: str = ""
    level: LevelId = "mid"
    company: str | None = Field(
        default=None,
        description="Optional company id - fuses the posting with that company's curated profile.",
    )
    role: str | None = Field(
        default=None, description="Optional role id, used with `company` for fusion."
    )
    persist: bool = True


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    analysis_id: int | None = None
    analysis: dict[str, Any] | None = Field(
        default=None, description="Inline analysis payload, if it was not persisted."
    )


class ChatResponse(BaseModel):
    answer: str
    intent: str
    suggested_questions: list[str]
    grounded: bool
    engine: str = "rule-based"


class ProjectRequest(BaseModel):
    missing_skills: list[str] = Field(min_length=1)
    role: str | None = None
    company: str | None = None
    level: LevelId = "entry"
    limit: int = Field(default=6, ge=1, le=20)


class AnalysisSummary(BaseModel):
    id: int
    resume_id: int
    company: str
    role: str
    level: str
    source: str
    overall_score: float
    ats_score: float
    band: str
    matched_count: int
    missing_count: int
    created_at: str


class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"
    hint: str | None = None
