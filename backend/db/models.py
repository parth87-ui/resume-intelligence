"""ORM models.

    User 1---* Resume 1---* ResumeAnalysis *---1 CompanyRequirement
                                  |
                                  +--* Recommendation
                                  +--* ProjectRecommendation

    Company 1---* CompanyRequirement *---1 JobRole
    Skill is the canonical ontology table, mirrored from datasets/skills.json.

JSON blobs are used for the analysis payloads (portable across SQLite and
PostgreSQL) while every entity that needs querying gets real columns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    candidate_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    linkedin: Mapped[str] = mapped_column(String(255), default="")
    github: Mapped[str] = mapped_column(String(255), default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["User | None"] = relationship(back_populates="resumes")
    analyses: Mapped[list["ResumeAnalysis"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    tagline: Mapped[str] = mapped_column(String(255), default="")
    values: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)

    requirements: Mapped[list["CompanyRequirement"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class JobRole(Base):
    __tablename__ = "job_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)

    requirements: Mapped[list["CompanyRequirement"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    related: Mapped[list] = mapped_column(JSON, default=list)
    learn_weeks: Mapped[int] = mapped_column(Integer, default=4)
    emerging: Mapped[bool] = mapped_column(Boolean, default=False)


class CompanyRequirement(Base):
    """A company x role x level requirement profile, curated or composed."""

    __tablename__ = "company_requirements"
    __table_args__ = (
        UniqueConstraint("company_id", "role_id", "level", name="uq_requirement_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("job_roles.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(32), default="entry")
    curated: Mapped[bool] = mapped_column(Boolean, default=False)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list] = mapped_column(JSON, default=list)
    optional_skills: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    responsibilities: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    company: Mapped["Company"] = relationship(back_populates="requirements")
    role: Mapped["JobRole"] = relationship(back_populates="requirements")
    analyses: Mapped[list["ResumeAnalysis"]] = relationship(back_populates="requirement")


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_requirements.id", ondelete="SET NULL"), nullable=True
    )
    company_slug: Mapped[str] = mapped_column(String(64), default="", index=True)
    role_slug: Mapped[str] = mapped_column(String(64), default="", index=True)
    level: Mapped[str] = mapped_column(String(32), default="entry")
    source: Mapped[str] = mapped_column(String(32), default="catalog")  # catalog | job-description
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    ats_score: Mapped[float] = mapped_column(Float, default=0.0)
    band: Mapped[str] = mapped_column(String(48), default="")
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    resume: Mapped["Resume"] = relationship(back_populates="analyses")
    requirement: Mapped["CompanyRequirement | None"] = relationship(back_populates="analyses")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    project_recommendations: Mapped[list["ProjectRecommendation"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class Recommendation(Base):
    """A resume improvement suggestion produced for one analysis."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("resume_analyses.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(48), default="")
    kind: Mapped[str] = mapped_column(String(32), default="rewrite")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    original: Mapped[str] = mapped_column(Text, default="")
    suggested: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=True)

    analysis: Mapped["ResumeAnalysis"] = relationship(back_populates="recommendations")


class ProjectRecommendation(Base):
    __tablename__ = "project_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("resume_analyses.id", ondelete="CASCADE"), index=True
    )
    project_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    difficulty: Mapped[str] = mapped_column(String(32), default="Intermediate")
    duration_weeks: Mapped[int] = mapped_column(Integer, default=4)
    fit_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    skills_closed: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    analysis: Mapped["ResumeAnalysis"] = relationship(back_populates="project_recommendations")
