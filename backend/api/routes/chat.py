"""Career assistant endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_session
from db.models import ResumeAnalysis
from schemas import ChatRequest, ChatResponse
from services.chat_service import get_chat_service

router = APIRouter(prefix="/api/chat", tags=["assistant"])


@router.post("", response_model=ChatResponse, summary="Ask a question about an analysis")
def chat(request: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    analysis = request.analysis
    if analysis is None and request.analysis_id is not None:
        row = session.get(ResumeAnalysis, request.analysis_id)
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"No analysis with id {request.analysis_id}."
            )
        analysis = row.payload

    result = get_chat_service().answer(request.question, analysis)
    return ChatResponse(
        answer=result["answer"],
        intent=result["intent"],
        suggested_questions=result["suggested_questions"],
        grounded=result["grounded"],
        engine=result.get("engine", "rule-based"),
    )


@router.get("/starters", summary="Suggested opening questions")
def starters() -> dict[str, list[str]]:
    return {
        "questions": [
            "Why is my compatibility score what it is?",
            "What skills should I learn first?",
            "Which project will improve my profile the most?",
            "How can I improve my resume without adding fake experience?",
            "What is blocking me from passing the ATS filter?",
            "How long until I am ready for this role?",
        ]
    }
