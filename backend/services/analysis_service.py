"""Analysis orchestration.

Single place where the full pipeline is executed:

    parsed resume
        -> skill extraction (NLP)
        -> requirement composition (company + role + level, or a pasted JD)
        -> matching & gap analysis
        -> weighted, explainable scoring
        -> ATS analysis
        -> AI improvement suggestions
        -> project recommendations
        -> learning roadmap
        -> chart-ready payloads

The API layer does nothing but validate input and call into here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ml.nlp_pipeline import get_pipeline
from ml.scoring_engine import ScoringEngine
from services.ai_service import get_ai_service
from services.ats_analyzer import get_ats_analyzer
from services.fit_evaluator import get_fit_evaluator
from services.job_matcher import MatchResult, get_job_matcher
from services.knowledge_base import JobRequirement, get_knowledge_base
from services.recommendation_engine import get_recommendation_engine
from services.resume_parser import ParsedResume
from services.section_scorer import get_section_scorer
from services.skill_extractor import get_skill_extractor


class AnalysisService:
    def __init__(self) -> None:
        self.kb = get_knowledge_base()
        self.extractor = get_skill_extractor()
        self.matcher = get_job_matcher()
        self.ats = get_ats_analyzer()
        self.ai = get_ai_service()
        self.recommender = get_recommendation_engine()
        self.sections = get_section_scorer()
        self.fit = get_fit_evaluator()
        self.nlp = get_pipeline()

    # -- public ------------------------------------------------------------

    def analyse_target(
        self, resume: ParsedResume, company_id: str, role_id: str, level_id: str
    ) -> dict[str, Any]:
        requirement = self.kb.build_requirement(company_id, role_id, level_id)
        return self.run(resume, requirement)

    def run(
        self,
        resume: ParsedResume,
        requirement: JobRequirement,
        jd_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skills = self.extractor.extract(resume)
        match = self.matcher.match(resume, skills, requirement)

        engine = ScoringEngine(requirement.weights)
        report = engine.score(match.components)

        ats = self.ats.analyse(resume, match)
        section_scores = self.sections.score(resume, match)
        fit = self.fit.evaluate(resume, match, report, jd_analysis)
        suggestions = self.ai.improve_resume(resume, match, ats)
        projects = self.recommender.recommend_projects(match, limit=6)
        roadmap = self.recommender.build_roadmap(match)
        skill_plan = self.recommender.skill_priority_plan(match)

        payload: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": requirement.to_dict(),
            "resume_overview": self._resume_overview(resume, skills),
            "scoring": report.to_dict(),
            "fit_assessment": fit,
            "ats": ats,
            "section_scores": section_scores,
            "skill_gap": match.gap_report(),
            "keyword_analysis": match.keyword_analysis,
            "experience_analysis": match.experience_analysis,
            "ai_suggestions": suggestions,
            "project_recommendations": projects,
            "learning_roadmap": roadmap,
            "skill_priority_plan": skill_plan,
            "charts": self._charts(match, report, ats, section_scores),
            "insights": self._insights(match, report, ats, section_scores, fit),
            "pipeline": {
                "nlp_backend": self.nlp.info(),
                "similarity_method": self.matcher.similarity.method,
                "ai_engine": self.ai.engine_info()["mode"],
                "stages": [
                    "resume parsing",
                    "NLP skill extraction",
                    "requirement composition",
                    "similarity & matching",
                    "weighted scoring",
                    "fit verdict",
                    "ATS analysis",
                    "AI suggestions",
                    "project recommendation",
                    "learning roadmap",
                ],
            },
        }
        if jd_analysis is not None:
            payload["job_description_analysis"] = jd_analysis
        return payload

    # -- sections ----------------------------------------------------------

    def _resume_overview(self, resume: ParsedResume, skills: list) -> dict[str, Any]:
        return {
            "contact": resume.contact,
            "metadata": resume.metadata,
            "skill_profile": self.extractor.profile_summary(skills),
            "skills_by_category": self.extractor.group_by_category(skills),
            "all_skills": [s.to_dict() for s in skills],
            "education": [
                {
                    "degree": e.degree,
                    "field": e.field_of_study,
                    "institution": e.institution,
                    "year": e.year,
                    "score": e.score,
                }
                for e in resume.education
            ],
            "experience": [
                {
                    "title": e.title,
                    "organisation": e.organisation,
                    "date_range": e.date_range,
                    "months": e.duration_months,
                    "bullets": e.bullets,
                }
                for e in resume.experience
            ],
            "projects": [
                {
                    "name": p.name,
                    "description": p.description,
                    "bullets": p.bullets,
                    "tech": p.tech_hint,
                }
                for p in resume.projects
            ],
            "certifications": resume.certifications,
            "achievements": resume.achievements,
            "sections_detected": resume.metadata.get("sections_detected", []),
        }

    def _charts(
        self,
        match: MatchResult,
        report,
        ats: dict[str, Any],
        section_scores: dict[str, Any],
    ) -> dict[str, Any]:
        counts = match.gap_report()["counts"]
        missing_bars = sorted(
            [
                m
                for m in match.matches
                if m.status in {"missing", "partial"} and m.tier != "optional"
            ],
            key=lambda m: -m.importance,
        )[:10]

        return {
            "gauge": {
                "value": round(report.overall, 1),
                "band": report.band,
                "thresholds": [40, 55, 70, 85],
            },
            "skill_pie": {
                "labels": ["Matched", "Partially matched", "Missing", "Optional gaps"],
                "values": [
                    counts["matched"],
                    counts["partial"],
                    counts["missing_high"] + counts["missing_medium"] + counts["missing_low"],
                    counts["optional"],
                ],
                "colors": ["#22c55e", "#f59e0b", "#ef4444", "#64748b"],
            },
            "radar": match.radar,
            "missing_bar": {
                "labels": [m.skill for m in missing_bars],
                "values": [round(m.importance * 100, 1) for m in missing_bars],
                "priorities": [m.priority for m in missing_bars],
                "statuses": [m.status for m in missing_bars],
            },
            "component_bars": [
                {
                    "label": c.label,
                    "score": round(c.score, 1),
                    "weight_percent": round(report.weights.get(c.key, 0) * 100, 1),
                }
                for c in report.components
            ],
            "ats_families": [
                {"label": v["label"], "score": v["score"]}
                for v in ats["family_scores"].values()
            ],
            "section_scores": [
                {"label": s["label"], "score": s["score"], "verdict": s["verdict"],
                 "key": s["key"]}
                for s in section_scores["sections"]
            ],
            "readiness": {
                "current": round(report.overall, 1),
                "after_presentation": self._projected_overall(
                    match, report, "after_presentation_fixes"
                ),
                "after_learning": self._projected_overall(
                    match, report, "after_closing_high_priority"
                ),
            },
        }

    def _projected_overall(self, match: MatchResult, report, key: str) -> float:
        """Overall score if the skills component improved to the projected value."""
        projection = self.recommender._project_score(
            match, match.missing_by_priority("high"), match.partial()
        )
        target_skills_score = projection[key]
        weights = report.weights
        recomputed = 0.0
        total = 0.0
        for component in report.components:
            weight = weights.get(component.key, 0.0)
            value = target_skills_score if component.key == "skills" else component.score
            recomputed += value * weight
            total += weight
        return round(recomputed / total, 1) if total else round(report.overall, 1)

    def _insights(
        self,
        match: MatchResult,
        report,
        ats: dict[str, Any],
        section_scores: dict[str, Any],
        fit: dict[str, Any],
    ) -> list[dict[str, str]]:
        req = match.requirement
        # The fit verdict leads: "should I apply?" is the question a candidate
        # asks before "what is my score?".
        insights: list[dict[str, str]] = [
            {
                "type": "fit",
                "title": f"{fit['verdict']} — {fit['confidence']:.0f}% confidence",
                "body": fit["headline"] + " " + fit["next_step"],
            },
            {
                "type": "score",
                "title": f"{report.overall:.0f}/100 — {report.band}",
                "body": report.narrative(),
            }
        ]

        high = match.missing_by_priority("high")
        if high:
            insights.append(
                {
                    "type": "gap",
                    "title": f"{len(high)} blocking gap(s) for {req.company_name}",
                    "body": (
                        ", ".join(m.skill for m in high[:5])
                        + f". These are treated as hard requirements for {req.role_title} "
                        f"at {req.company_name}, so they cost the most points."
                    ),
                }
            )
        else:
            insights.append(
                {
                    "type": "strength",
                    "title": "All high-priority requirements evidenced",
                    "body": (
                        f"Every hard requirement for {req.company_name} {req.role_title} appears "
                        "in your resume. Focus your remaining effort on depth and measurable results."
                    ),
                }
            )

        partial = [m for m in match.partial() if not m.via]
        if partial:
            insights.append(
                {
                    "type": "quick-win",
                    "title": f"{len(partial)} skill(s) you already have are hidden",
                    "body": (
                        ", ".join(m.skill for m in partial[:5])
                        + " appear only in your skills list. Moving them into a real bullet raises "
                        "your score without learning anything new."
                    ),
                }
            )

        weakest = min(section_scores["sections"], key=lambda s: s["score"])
        if weakest["score"] < 70:
            insights.append(
                {
                    "type": "section",
                    "title": f"Weakest section: {weakest['label']} ({weakest['score']:.0f}/100)",
                    "body": (
                        section_scores["summary"]
                        + " Section scores tell you which part of the document to edit."
                    ),
                }
            )

        if ats["score"] < 70:
            insights.append(
                {
                    "type": "ats",
                    "title": f"ATS score {ats['score']:.0f}/100 — {ats['band']}",
                    "body": ats["summary"],
                }
            )

        if req.screen_notes:
            insights.append(
                {"type": "company", "title": f"How {req.company_name} screens", "body": req.screen_notes}
            )
        return insights


_SERVICE: AnalysisService | None = None


def get_analysis_service() -> AnalysisService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = AnalysisService()
    return _SERVICE
