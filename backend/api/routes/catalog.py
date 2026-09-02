"""Catalog endpoints - the company / role / level / skill knowledge base."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ml.scoring_engine import COMPONENT_METHODS, DEFAULT_WEIGHTS
from schemas import CatalogResponse
from services.knowledge_base import get_knowledge_base

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("", response_model=CatalogResponse, summary="Everything needed to build the target picker")
def get_catalog() -> CatalogResponse:
    kb = get_knowledge_base()
    return CatalogResponse(
        companies=kb.list_companies(),
        roles=kb.list_roles(),
        levels=kb.list_levels(),
        skill_count=len(kb.skills),
        project_count=len(kb.projects),
        scoring_weights=DEFAULT_WEIGHTS,
    )


@router.get("/companies", summary="List supported companies")
def list_companies() -> list[dict[str, Any]]:
    return get_knowledge_base().list_companies()


@router.get("/roles", summary="List supported job roles")
def list_roles() -> list[dict[str, Any]]:
    return get_knowledge_base().list_roles()


@router.get("/levels", summary="List experience levels and their scoring weights")
def list_levels() -> list[dict[str, Any]]:
    return get_knowledge_base().list_levels()


@router.get("/skills", summary="The full skill ontology")
def list_skills(
    category: str | None = Query(default=None, description="Filter by category id."),
    search: str | None = Query(default=None, description="Case-insensitive name/alias search."),
) -> dict[str, Any]:
    kb = get_knowledge_base()
    skills = kb.list_skills()
    if category:
        skills = [s for s in skills if s["category"] == category]
    if search:
        needle = search.lower()
        skills = [
            s
            for s in skills
            if needle in s["name"].lower() or any(needle in a for a in s["aliases"])
        ]
    return {"categories": kb.skill_categories, "count": len(skills), "skills": skills}


@router.get("/projects", summary="The project catalogue used by the recommender")
def list_projects() -> dict[str, Any]:
    projects = get_knowledge_base().projects
    return {"count": len(projects), "projects": projects}


@router.get("/scoring", summary="How the overall score is calculated")
def scoring_methodology() -> dict[str, Any]:
    kb = get_knowledge_base()
    return {
        "formula": "overall = Σ (component_score × weight) ÷ Σ weights",
        "default_weights": DEFAULT_WEIGHTS,
        "component_methods": COMPONENT_METHODS,
        "level_weights": {level["id"]: level["weights"] for level in kb.levels.values()},
        "credit_rules": {
            "applied in experience or projects": 1.0,
            "declared in the skills section only": 0.8,
            "evidenced only through a related skill": 0.5,
            "not evidenced": 0.0,
        },
        "bands": [
            {"min": 85, "label": "Excellent Match"},
            {"min": 70, "label": "Strong Match"},
            {"min": 55, "label": "Moderate Match"},
            {"min": 40, "label": "Developing Match"},
            {"min": 0, "label": "Early Stage"},
        ],
    }


@router.get(
    "/requirements/{company_id}/{role_id}",
    summary="The composed requirement profile for a target",
)
def get_requirements(company_id: str, role_id: str, level: str = "entry") -> dict[str, Any]:
    kb = get_knowledge_base()
    try:
        requirement = kb.build_requirement(company_id, role_id, level)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return requirement.to_dict()
