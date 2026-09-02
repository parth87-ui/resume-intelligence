"""Resume upload and parsing endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import UPLOAD_DIR, settings
from db.database import get_session
from db.models import Resume
from schemas import UploadResponse
from services.resume_parser import ResumeParsingError, get_resume_parser
from services.skill_extractor import get_skill_extractor

router = APIRouter(prefix="/api/resume", tags=["resume"])


def _validate_upload(file: UploadFile, data: bytes) -> None:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix or 'unknown'}'. "
                f"Allowed: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}."
            ),
        )
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File is {len(data) / 1_048_576:.1f} MB; the limit is "
                f"{settings.MAX_UPLOAD_MB:.0f} MB."
            ),
        )


def _persist(session: Session, filename: str, parsed) -> int:
    row = Resume(
        file_name=filename,
        file_type=parsed.metadata.get("file_type", ""),
        candidate_name=parsed.contact.get("name", ""),
        email=parsed.contact.get("email", ""),
        phone=parsed.contact.get("phone", ""),
        linkedin=parsed.contact.get("linkedin", ""),
        github=parsed.contact.get("github", ""),
        word_count=parsed.metadata.get("words", 0),
        raw_text=parsed.raw_text,
        parsed=parsed.to_dict(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.id


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Upload and parse a resume (PDF, DOCX or TXT)",
)
async def upload_resume(
    file: UploadFile = File(..., description="PDF, DOCX or TXT, max 10 MB"),
    session: Session = Depends(get_session),
) -> UploadResponse:
    data = await file.read()
    _validate_upload(file, data)

    parser = get_resume_parser()
    try:
        parsed = parser.parse(data, file.filename or "resume.pdf")
    except ResumeParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected parser failure
        raise HTTPException(
            status_code=500, detail=f"Unexpected error while parsing the resume: {exc}"
        ) from exc

    if settings.STORE_UPLOADED_FILES:
        try:
            (UPLOAD_DIR / f"{file.filename}").write_bytes(data)
        except OSError:
            pass  # storing the original file is a convenience, never required

    skills = get_skill_extractor().extract(parsed)
    resume_id = _persist(session, file.filename or "resume.pdf", parsed)

    return UploadResponse(
        resume_id=resume_id,
        file_name=file.filename or "resume.pdf",
        contact=parsed.contact,
        sections_detected=parsed.metadata.get("sections_detected", []),
        skills_detected=[s.name for s in skills],
        skill_profile=get_skill_extractor().profile_summary(skills),
        metadata=parsed.metadata,
        warnings=parsed.metadata.get("warnings", []),
        parsed=parsed.to_dict(),
    )


@router.post("/parse-text", response_model=UploadResponse, summary="Parse pasted resume text")
def parse_resume_text(
    resume_text: str = Form(..., description="Raw resume text"),
    session: Session = Depends(get_session),
) -> UploadResponse:
    if len(resume_text.split()) < 40:
        raise HTTPException(
            status_code=422, detail="Resume text is too short to analyse (minimum 40 words)."
        )
    parsed = get_resume_parser().parse_text(resume_text)
    skills = get_skill_extractor().extract(parsed)
    resume_id = _persist(session, "pasted-resume.txt", parsed)
    return UploadResponse(
        resume_id=resume_id,
        file_name="pasted-resume.txt",
        contact=parsed.contact,
        sections_detected=parsed.metadata.get("sections_detected", []),
        skills_detected=[s.name for s in skills],
        skill_profile=get_skill_extractor().profile_summary(skills),
        metadata=parsed.metadata,
        warnings=parsed.metadata.get("warnings", []),
        parsed=parsed.to_dict(),
    )


@router.get("/{resume_id}", summary="Retrieve a stored parsed resume")
def get_resume(resume_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(Resume, resume_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No resume with id {resume_id}.")
    return {
        "resume_id": row.id,
        "file_name": row.file_name,
        "created_at": row.created_at.isoformat(),
        "contact": {
            "name": row.candidate_name,
            "email": row.email,
            "phone": row.phone,
            "linkedin": row.linkedin,
            "github": row.github,
        },
        "parsed": row.parsed,
    }


@router.delete("/{resume_id}", summary="Delete a stored resume and its analyses")
def delete_resume(resume_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(Resume, resume_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No resume with id {resume_id}.")
    session.delete(row)
    session.commit()
    return {"deleted": resume_id}
