"""Project recommendation and learning-roadmap generation.

Projects are ranked by how much *weighted* gap they actually close for the
selected target, not by generic popularity:

    fit = 0.55 * importance-weighted coverage of the candidate's gaps
        + 0.15 * role affinity
        + 0.10 * company affinity
        + 0.12 * difficulty suitability for the experience level
        + 0.08 * emerging-skill bonus

The roadmap then sequences the gaps into phases with realistic week estimates
taken from the skill ontology, and projects the score improvement that closing
each phase would produce - using the same scoring maths as the live analysis,
never an invented number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.job_matcher import MatchResult, SkillMatch
from services.knowledge_base import KnowledgeBase, get_knowledge_base

DIFFICULTY_FIT: dict[str, dict[str, float]] = {
    # level -> difficulty -> suitability
    "intern": {"Beginner": 1.0, "Intermediate": 0.75, "Advanced": 0.35},
    "entry": {"Beginner": 0.85, "Intermediate": 1.0, "Advanced": 0.55},
    "mid": {"Beginner": 0.45, "Intermediate": 1.0, "Advanced": 0.9},
    "senior": {"Beginner": 0.2, "Intermediate": 0.7, "Advanced": 1.0},
}


@dataclass
class ProjectRecommendation:
    project: dict[str, Any]
    fit: float
    skills_closed: list[str]
    weighted_gap_closed: float
    priority: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        p = self.project
        return {
            "id": p["id"],
            "title": p["title"],
            "description": p["description"],
            "difficulty": p["difficulty"],
            "duration_weeks": p["duration_weeks"],
            "estimated_duration": f"{p['duration_weeks']} weeks",
            "skills_gained": p["skills_taught"],
            "skills_closed": self.skills_closed,
            "prerequisites": p.get("prerequisites", []),
            "learning_objectives": p.get("objectives", []),
            "deliverables": p.get("deliverables", []),
            "verification": p.get("verification", ""),
            "resume_bullet_template": p.get("resume_bullet_template", ""),
            "fit_score": round(self.fit * 100, 1),
            "gap_coverage": round(self.weighted_gap_closed * 100, 1),
            "priority": self.priority,
            "rationale": self.rationale,
        }


class RecommendationEngine:
    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or get_knowledge_base()

    # -- projects ----------------------------------------------------------

    def recommend_projects(self, match: MatchResult, limit: int = 6) -> list[dict[str, Any]]:
        gaps = [
            m for m in match.matches if m.status in {"missing", "partial"}
        ]
        if not gaps:
            return []

        gap_weight = {m.skill: m.importance * (1.0 if m.status == "missing" else 0.4) for m in gaps}
        total_gap_weight = sum(gap_weight.values()) or 1.0
        req = match.requirement
        level_fit = DIFFICULTY_FIT.get(req.level_id, DIFFICULTY_FIT["entry"])

        ranked: list[ProjectRecommendation] = []
        for project in self.kb.projects:
            taught = {self.kb.canonical_skill(s) or s for s in project["skills_taught"]}
            closed = sorted(taught & set(gap_weight.keys()))
            if not closed:
                continue

            covered_weight = sum(gap_weight[s] for s in closed)
            coverage = covered_weight / total_gap_weight
            role_affinity = 1.0 if req.role_id in project.get("roles", []) else 0.35
            company_affinity = 1.0 if req.company_id in project.get("companies", []) else 0.4
            difficulty = level_fit.get(project.get("difficulty", "Intermediate"), 0.6)
            emerging_bonus = (
                1.0 if any(self.kb.is_emerging(s) for s in closed) else 0.3
            )

            fit = (
                0.55 * min(1.0, coverage * 2.5)
                + 0.15 * role_affinity
                + 0.10 * company_affinity
                + 0.12 * difficulty
                + 0.08 * emerging_bonus
            )

            high_priority_closed = [
                m.skill for m in gaps if m.skill in closed and m.priority == "high"
            ]
            priority = (
                "high" if high_priority_closed else ("medium" if coverage > 0.08 else "low")
            )
            rationale = self._rationale(req, closed, high_priority_closed, project)
            ranked.append(
                ProjectRecommendation(
                    project=project,
                    fit=min(1.0, fit),
                    skills_closed=closed,
                    weighted_gap_closed=coverage,
                    priority=priority,
                    rationale=rationale,
                )
            )

        ranked.sort(key=lambda r: (-_priority_rank(r.priority), -r.fit))
        return [r.to_dict() for r in ranked[:limit]]

    def _rationale(
        self,
        req,
        closed: list[str],
        high_priority: list[str],
        project: dict[str, Any],
    ) -> str:
        if high_priority:
            return (
                f"Closes {len(high_priority)} high-priority gap(s) for {req.company_name} "
                f"{req.role_title}: {', '.join(high_priority[:4])}."
            )
        return (
            f"Adds {', '.join(closed[:4])}, which appear in the "
            f"{req.company_name} {req.role_title} profile."
        )

    # -- learning roadmap --------------------------------------------------

    def build_roadmap(self, match: MatchResult) -> dict[str, Any]:
        req = match.requirement
        high = match.missing_by_priority("high")
        medium = match.missing_by_priority("medium")
        low = [m for m in match.missing_by_priority("low") if m.tier != "optional"]
        partial = match.partial()
        projects = self.recommend_projects(match, limit=4)

        phases: list[dict[str, Any]] = []

        # Phase 0 - things that cost nothing but honesty and editing time.
        if partial:
            phases.append(
                {
                    "phase": 1,
                    "title": "Surface what you already have",
                    "duration_weeks": 1,
                    "type": "resume",
                    "why": (
                        "These skills are already in your resume but are not visible where it "
                        "counts. This phase changes presentation only - no new learning, and "
                        "nothing invented."
                    ),
                    "actions": [
                        {
                            "action": f"Show {m.skill} inside a real experience or project bullet",
                            "detail": m.reason,
                            "skill": m.skill,
                        }
                        for m in partial[:6]
                    ],
                    "skills": [m.skill for m in partial[:6]],
                }
            )

        if high:
            weeks = _phase_weeks(high[:4])
            phases.append(
                {
                    "phase": len(phases) + 1,
                    "title": "Close the blocking gaps",
                    "duration_weeks": weeks,
                    "type": "learning",
                    "why": (
                        f"These are treated as hard requirements for {req.company_name} "
                        f"{req.role_title}. Applications are most often filtered here."
                    ),
                    "actions": [
                        {
                            "action": f"Learn {m.skill}",
                            "detail": (
                                f"Roughly {m.learn_weeks} weeks of focused study. "
                                f"{'Adjacent to your ' + m.via + ' experience.' if m.via else ''}"
                            ).strip(),
                            "skill": m.skill,
                            "estimated_weeks": m.learn_weeks,
                        }
                        for m in high[:4]
                    ],
                    "skills": [m.skill for m in high[:4]],
                }
            )

        if projects:
            phases.append(
                {
                    "phase": len(phases) + 1,
                    "title": "Prove it with a project",
                    "duration_weeks": projects[0]["duration_weeks"],
                    "type": "project",
                    "why": (
                        "A finished, verifiable project is the only honest way to put a new skill "
                        "on your resume. Add the bullet after you ship it, never before."
                    ),
                    "actions": [
                        {
                            "action": f"Build: {p['title']}",
                            "detail": f"{p['difficulty']} · {p['estimated_duration']} · closes "
                            + ", ".join(p["skills_closed"][:4]),
                            "project_id": p["id"],
                            "estimated_weeks": p["duration_weeks"],
                        }
                        for p in projects[:2]
                    ],
                    "skills": sorted({s for p in projects[:2] for s in p["skills_closed"]}),
                }
            )

        if medium or low:
            tail = (medium + low)[:5]
            phases.append(
                {
                    "phase": len(phases) + 1,
                    "title": "Broaden and differentiate",
                    "duration_weeks": _phase_weeks(tail),
                    "type": "learning",
                    "why": (
                        "Frequently-requested skills that separate comparable candidates once the "
                        "blocking gaps are closed."
                    ),
                    "actions": [
                        {
                            "action": f"Learn {m.skill}",
                            "detail": f"{m.priority.title()} priority · about {m.learn_weeks} weeks",
                            "skill": m.skill,
                            "estimated_weeks": m.learn_weeks,
                        }
                        for m in tail
                    ],
                    "skills": [m.skill for m in tail],
                }
            )

        emerging = match.emerging_gaps()
        if emerging:
            phases.append(
                {
                    "phase": len(phases) + 1,
                    "title": "Stay ahead of the curve",
                    "duration_weeks": _phase_weeks(emerging[:3]),
                    "type": "emerging",
                    "why": (
                        "Fast-growing skills that few candidates at your level can evidence yet. "
                        "These are differentiators rather than requirements."
                    ),
                    "actions": [
                        {
                            "action": f"Explore {m.skill}",
                            "detail": f"Emerging in this role · about {m.learn_weeks} weeks",
                            "skill": m.skill,
                            "estimated_weeks": m.learn_weeks,
                        }
                        for m in emerging[:3]
                    ],
                    "skills": [m.skill for m in emerging[:3]],
                }
            )

        total_weeks = sum(p["duration_weeks"] for p in phases)
        projection = self._project_score(match, high, partial)

        return {
            "target": f"{req.company_name} · {req.role_title} · {req.level_title}",
            "current_state": {
                "matched_skills": [m.skill for m in match.matched()][:12],
                "matched_count": len(match.matched()),
                "gap_count": len(match.missing(("required", "preferred"))),
            },
            "phases": phases,
            "total_duration_weeks": total_weeks,
            "estimated_completion": _human_duration(total_weeks),
            "projection": projection,
            "principle": (
                "Every step here adds a real capability first and a resume line second. "
                "Nothing in this roadmap asks you to claim something you have not done."
            ),
        }

    def _project_score(
        self, match: MatchResult, high: list[SkillMatch], partial: list[SkillMatch]
    ) -> dict[str, Any]:
        """Recompute the skills component under 'gaps closed' assumptions.

        This uses the live scoring formula rather than an arbitrary uplift, so
        the projected number is defensible.
        """
        matches = match.matches
        total = sum(m.importance for m in matches) or 1.0
        current = sum(m.importance * m.credit for m in matches)

        after_presentation = current + sum(
            m.importance * (1.0 - m.credit) for m in partial
        )
        after_learning = after_presentation + sum(m.importance for m in high)

        return {
            "current_skills_score": round((current / total) * 100, 1),
            "after_presentation_fixes": round(min(100.0, (after_presentation / total) * 100), 1),
            "after_closing_high_priority": round(min(100.0, (after_learning / total) * 100), 1),
            "note": (
                "Projected using the same importance-weighted formula as the live score, "
                "assuming each listed gap is genuinely closed and evidenced."
            ),
        }

    # -- skill-level guidance ---------------------------------------------

    def skill_priority_plan(self, match: MatchResult) -> list[dict[str, Any]]:
        """Ordered 'what to learn first' list with reasons."""
        gaps = [m for m in match.matches if m.status in {"missing", "partial"}]
        ordered = sorted(
            gaps,
            key=lambda m: (
                -_priority_rank(m.priority),
                -m.importance,
                m.learn_weeks,
            ),
        )
        plan: list[dict[str, Any]] = []
        cumulative = 0
        for index, m in enumerate(ordered[:12], start=1):
            weeks = m.learn_weeks if m.status == "missing" else 1
            cumulative += weeks
            plan.append(
                {
                    "order": index,
                    "skill": m.skill,
                    "category": m.category_label,
                    "status": m.status,
                    "priority": m.priority,
                    "importance": round(m.importance, 2),
                    "estimated_weeks": weeks,
                    "cumulative_weeks": cumulative,
                    "why": m.reason
                    or f"{m.priority.title()}-priority requirement for this target",
                    "related_skills": self.kb.related_skills(m.skill)[:4],
                }
            )
        return plan


def _priority_rank(priority: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(priority, 0)


def _phase_weeks(matches: list[SkillMatch]) -> int:
    if not matches:
        return 0
    # Skills are learned partly in parallel: the longest sets the pace, the
    # rest add half their time.
    weeks = [m.learn_weeks for m in matches]
    return int(max(weeks) + 0.5 * sum(sorted(weeks)[:-1]))


def _human_duration(weeks: int) -> str:
    if weeks <= 0:
        return "no additional learning required"
    if weeks < 8:
        return f"about {weeks} weeks"
    months = round(weeks / 4.345)
    return f"about {months} month{'s' if months != 1 else ''}"


_ENGINE: RecommendationEngine | None = None


def get_recommendation_engine() -> RecommendationEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RecommendationEngine()
    return _ENGINE
