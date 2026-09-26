"""Analysis endpoints - the core of the platform."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.database import get_session
from db.models import ProjectRecommendation, Recommendation, Resume, ResumeAnalysis
from db.seed import ensure_requirement_row
from schemas import AnalyseRequest, AnalysisSummary, JobDescriptionRequest, ProjectRequest
from services.analysis_service import get_analysis_service
from services.jd_parser import NonTechJobDescriptionError, get_jd_parser
from services.knowledge_base import get_knowledge_base
from services.recommendation_engine import get_recommendation_engine
from services.resume_parser import ParsedResume, get_resume_parser

router = APIRouter(prefix="/api", tags=["analysis"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_resume(
    session: Session, resume_id: int | None, resume_text: str | None
) -> tuple[ParsedResume, int | None]:
    """Resolve a request into a parsed resume, from storage or raw text."""
    if resume_id is not None:
        row = session.get(Resume, resume_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"No resume with id {resume_id}.")
        parsed = get_resume_parser().parse_text(row.raw_text, filename=row.file_name)
        return parsed, row.id
    if resume_text:
        return get_resume_parser().parse_text(resume_text), None
    raise HTTPException(
        status_code=400,
        detail="Provide either resume_id (from /api/resume/upload) or resume_text.",
    )


def _store_analysis(
    session: Session,
    resume_id: int | None,
    payload: dict[str, Any],
    company_slug: str,
    role_slug: str,
    level: str,
    source: str,
) -> int | None:
    """Persist an analysis together with its recommendations."""
    if resume_id is None:
        return None

    requirement_row = None
    if source == "catalog":
        requirement_row = ensure_requirement_row(session, company_slug, role_slug, level)

    counts = payload["skill_gap"]["counts"]
    analysis = ResumeAnalysis(
        resume_id=resume_id,
        requirement_id=requirement_row.id if requirement_row else None,
        company_slug=company_slug,
        role_slug=role_slug,
        level=level,
        source=source,
        overall_score=payload["scoring"]["overall_score"],
        ats_score=payload["ats"]["score"],
        band=payload["scoring"]["band"],
        matched_count=counts["matched"],
        missing_count=counts["missing_high"] + counts["missing_medium"] + counts["missing_low"],
        payload=payload,
    )
    session.add(analysis)
    session.flush()

    for section, items in payload["ai_suggestions"]["sections"].items():
        for item in items:
            session.add(
                Recommendation(
                    analysis_id=analysis.id,
                    section=section,
                    kind=item["kind"],
                    priority="high" if "high-impact" in item.get("tags", []) else "medium",
                    original=item["original"][:4000],
                    suggested=item["suggested"][:4000],
                    rationale=item["rationale"][:4000],
                    requires_verification=item["requires_verification"],
                )
            )

    for project in payload["project_recommendations"]:
        session.add(
            ProjectRecommendation(
                analysis_id=analysis.id,
                project_key=project["id"],
                title=project["title"],
                difficulty=project["difficulty"],
                duration_weeks=project["duration_weeks"],
                fit_score=project["fit_score"],
                priority=project["priority"],
                skills_closed=project["skills_closed"],
                payload=project,
            )
        )

    session.commit()
    return analysis.id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/analyze", summary="Full company- and role-specific resume analysis")
def analyze(request: AnalyseRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    kb = get_knowledge_base()
    if request.company not in kb.companies:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown company '{request.company}'. See GET /api/catalog/companies.",
        )
    if request.role not in kb.roles:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown role '{request.role}'. See GET /api/catalog/roles.",
        )

    parsed, resume_id = _load_resume(session, request.resume_id, request.resume_text)
    payload = get_analysis_service().analyse_target(
        parsed, request.company, request.role, request.level
    )

    analysis_id = None
    if request.persist:
        analysis_id = _store_analysis(
            session, resume_id, payload, request.company, request.role, request.level, "catalog"
        )
    payload["analysis_id"] = analysis_id
    payload["resume_id"] = resume_id
    return payload


@router.post(
    "/analyze/job-description",
    summary="Analyse a resume against a pasted job description",
)
def analyze_job_description(
    request: JobDescriptionRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    parsed, resume_id = _load_resume(session, request.resume_id, request.resume_text)
    jd_parser = get_jd_parser()
    try:
        requirement, jd_analysis = jd_parser.parse(
            request.job_description,
            company_name=request.company_name,
            role_title=request.role_title,
            level_id=request.level,
        )
    except NonTechJobDescriptionError as exc:
        # Answered with an explicit code rather than a bare 422 so the UI can
        # tell "not a tech posting" apart from "the posting was unparseable"
        # and keep the user on the target page instead of navigating away.
        return JSONResponse(
            status_code=422,
            content={
                "detail": str(exc),
                "code": "non_tech_jd",
                "domain": exc.domain,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    kb = get_knowledge_base()
    fused = False
    if request.company and request.role:
        if request.company not in kb.companies or request.role not in kb.roles:
            raise HTTPException(
                status_code=404, detail="Unknown company or role id for fusion."
            )
        requirement = jd_parser.fuse_with_target(
            requirement, request.company, request.role, request.level
        )
        fused = True

    payload = get_analysis_service().run(parsed, requirement, jd_analysis=jd_analysis)
    payload["job_description_analysis"]["fused_with_company_profile"] = fused

    analysis_id = None
    if request.persist:
        analysis_id = _store_analysis(
            session,
            resume_id,
            payload,
            request.company or "custom",
            request.role or "custom",
            request.level,
            "job-description",
        )
    payload["analysis_id"] = analysis_id
    payload["resume_id"] = resume_id
    return payload


@router.get("/analysis/{analysis_id}", summary="Retrieve a stored analysis")
def get_analysis(analysis_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(ResumeAnalysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No analysis with id {analysis_id}.")
    payload = dict(row.payload)
    payload["analysis_id"] = row.id
    payload["resume_id"] = row.resume_id
    return payload


@router.get("/analyses", summary="List stored analyses")
def list_analyses(
    resume_id: int | None = None, limit: int = 20, session: Session = Depends(get_session)
) -> list[AnalysisSummary]:
    statement = select(ResumeAnalysis).order_by(ResumeAnalysis.created_at.desc()).limit(limit)
    if resume_id is not None:
        statement = statement.where(ResumeAnalysis.resume_id == resume_id)
    rows = session.scalars(statement).all()
    return [
        AnalysisSummary(
            id=row.id,
            resume_id=row.resume_id,
            company=row.company_slug,
            role=row.role_slug,
            level=row.level,
            source=row.source,
            overall_score=row.overall_score,
            ats_score=row.ats_score,
            band=row.band,
            matched_count=row.matched_count,
            missing_count=row.missing_count,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/projects/recommend", summary="Recommend projects for an explicit skill gap")
def recommend_projects(request: ProjectRequest) -> dict[str, Any]:
    """Standalone recommender - useful without a full analysis."""
    kb = get_knowledge_base()
    canonical = []
    unknown = []
    for name in request.missing_skills:
        resolved = kb.canonical_skill(name)
        (canonical if resolved else unknown).append(resolved or name)

    if not canonical:
        raise HTTPException(
            status_code=422,
            detail=f"None of these skills are in the ontology: {', '.join(unknown)}.",
        )

    scored: list[dict[str, Any]] = []
    for project in kb.projects:
        taught = {kb.canonical_skill(s) or s for s in project["skills_taught"]}
        closed = sorted(taught & set(canonical))
        if not closed:
            continue
        role_affinity = 1.0 if request.role and request.role in project.get("roles", []) else 0.4
        company_affinity = (
            1.0 if request.company and request.company in project.get("companies", []) else 0.4
        )
        coverage = len(closed) / len(canonical)
        fit = 0.6 * coverage + 0.25 * role_affinity + 0.15 * company_affinity
        scored.append(
            {
                "id": project["id"],
                "title": project["title"],
                "description": project["description"],
                "difficulty": project["difficulty"],
                "duration_weeks": project["duration_weeks"],
                "estimated_duration": f"{project['duration_weeks']} weeks",
                "skills_gained": project["skills_taught"],
                "skills_closed": closed,
                "learning_objectives": project.get("objectives", []),
                "deliverables": project.get("deliverables", []),
                "verification": project.get("verification", ""),
                "resume_bullet_template": project.get("resume_bullet_template", ""),
                "fit_score": round(fit * 100, 1),
                "gap_coverage": round(coverage * 100, 1),
                "priority": "high" if coverage >= 0.5 else "medium",
                "rationale": f"Teaches {', '.join(closed[:4])} from your stated gap list.",
            }
        )

    scored.sort(key=lambda p: -p["fit_score"])
    return {
        "resolved_skills": canonical,
        "unrecognised_skills": unknown,
        "count": len(scored[: request.limit]),
        "projects": scored[: request.limit],
    }


@router.get("/roadmap/{analysis_id}", summary="Retrieve the learning roadmap for an analysis")
def get_roadmap(analysis_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(ResumeAnalysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No analysis with id {analysis_id}.")
    return {
        "analysis_id": row.id,
        "roadmap": row.payload.get("learning_roadmap", {}),
        "skill_priority_plan": row.payload.get("skill_priority_plan", []),
        "projects": row.payload.get("project_recommendations", []),
    }
