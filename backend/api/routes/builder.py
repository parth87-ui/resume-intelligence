"""Resume builder endpoints.

Two operations, both thin: validate the request, call a service, return the
result. All generation logic lives in ``services/resume_builder.py`` and all
document rendering in ``services/resume_export.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from db.database import get_session
from db.models import Resume, ResumeAnalysis
from schemas import BuildResumeRequest, ExportResumeRequest
from services.knowledge_base import JobRequirement, get_knowledge_base
from services.resume_builder import BuildOptions, get_resume_builder
from services.resume_export import (
    CONTENT_TYPES,
    ResumeExportError,
    render,
    safe_file_name,
)
from services.resume_parser import get_resume_parser

router = APIRouter(prefix="/api/resume", tags=["builder"])

# Buckets a skill may come from. Everything the resume does not already
# evidence is fair game to confirm or mark as being learned; a skill it already
# evidences is not, because "adding" it would be meaningless.
GAP_BUCKETS = (
    "missing_high_priority",
    "missing_medium_priority",
    "missing_low_priority",
    "optional",
    "emerging",
    "partially_matched",
)


def _gap_skills(payload: dict[str, Any]) -> dict[str, str]:
    """Canonical-lowercase -> display name, for every skill the user may claim."""
    gap = payload.get("skill_gap") or {}
    allowed: dict[str, str] = {}
    for bucket in GAP_BUCKETS:
        for item in gap.get(bucket, []):
            name = item.get("skill", "")
            if name:
                allowed[name.lower()] = name
    return allowed


def _validate_claimed(
    names: list[str], allowed: dict[str, str], field_name: str
) -> list[str]:
    """Map user-supplied names onto the analysis's own gap list."""
    kb = get_knowledge_base()
    resolved: list[str] = []
    unknown: list[str] = []
    for raw in names:
        candidate = (kb.canonical_skill(raw) or raw).strip()
        match = allowed.get(candidate.lower())
        if match is None:
            unknown.append(raw)
        else:
            resolved.append(match)

    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field_name} contains skill(s) that are not gaps in this analysis: "
                f"{', '.join(unknown)}. Only skills the resume does not already "
                "evidence can be confirmed or marked as in progress."
            ),
        )
    return resolved


@router.post("/build", summary="Generate an improved resume for a stored analysis")
def build_resume(
    request: BuildResumeRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    analysis = session.get(ResumeAnalysis, request.analysis_id)
    if analysis is None:
        raise HTTPException(
            status_code=404, detail=f"No analysis with id {request.analysis_id}."
        )

    resume_row = session.get(Resume, analysis.resume_id)
    if resume_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"The resume behind analysis {request.analysis_id} no longer exists.",
        )

    payload = analysis.payload or {}
    target = payload.get("target")
    if not target:
        raise HTTPException(
            status_code=422,
            detail="This stored analysis has no target profile, so it cannot be rebuilt.",
        )

    allowed = _gap_skills(payload)
    confirmed = _validate_claimed(request.confirmed_skills, allowed, "confirmed_skills")
    learning = _validate_claimed(request.learning_skills, allowed, "learning_skills")

    overlap = sorted(set(confirmed) & set(learning))
    if overlap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{', '.join(overlap)} cannot be both confirmed and still being learned. "
                "Pick one."
            ),
        )

    # A pasted job description exists only inside the stored payload, so the
    # requirement is rebuilt from it rather than recomposed from the datasets.
    requirement = JobRequirement.from_dict(target)
    parsed = get_resume_parser().parse_text(
        resume_row.raw_text, filename=resume_row.file_name
    )

    known_projects = {p["id"] for p in get_knowledge_base().projects}
    unknown = [
        pid
        for pid in (*request.projects_built, *request.projects_in_progress)
        if pid not in known_projects
    ]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown project id(s): {', '.join(unknown)}.",
        )
    both = sorted(set(request.projects_built) & set(request.projects_in_progress))
    if both:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{', '.join(both)} cannot be both finished and in progress. Pick one."
            ),
        )

    result = get_resume_builder().build(
        parsed,
        requirement,
        BuildOptions(
            mode=request.mode,
            confirmed_skills=confirmed,
            learning_skills=learning,
            details=request.details.model_dump(),
            projects_built=list(request.projects_built),
            projects_in_progress=list(request.projects_in_progress),
        ),
    )
    result["analysis_id"] = analysis.id
    result["resume_id"] = resume_row.id
    return result


@router.post(
    "/export",
    summary="Download the resume as DOCX, PDF or TXT",
    response_class=Response,
    responses={
        200: {
            "content": {ctype.split(";")[0]: {} for ctype in CONTENT_TYPES.values()},
            "description": "The generated document as a file download.",
        }
    },
)
def export_resume(request: ExportResumeRequest) -> Response:
    try:
        data = render(
            request.text, request.format, strip=request.strip_placeholders
        )
    except ResumeExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = safe_file_name(request.file_name, request.format)
    return Response(
        content=data,
        media_type=CONTENT_TYPES[request.format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
            # The browser reads the name from the header, which is not exposed
            # cross-origin unless it is listed here.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
