"""Job matching and skill-gap analysis.

Compares an extracted resume profile against a composed job requirement and
produces:

    * five skill buckets - matched, partially matched, missing (by priority),
      optional and emerging
    * the six component scores consumed by the scoring engine
    * keyword analysis and an experience-gap read

Credit rules (the reason a score is what it is):

    applied in experience/projects .......... 1.00
    declared in the skills section only ..... 0.80   (partial - listed, not demonstrated)
    evidenced only through an applied related skill  0.35   (partial - adjacent only)
    not evidenced ........................... 0.00
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ml.nlp_pipeline import find_metrics
from ml.scoring_engine import ComponentScore, clamp_score
from ml.similarity_model import get_similarity_model
from services.knowledge_base import JobRequirement, KnowledgeBase, get_knowledge_base
from services.resume_parser import ParsedResume
from services.skill_extractor import ExtractedSkill, get_skill_extractor

CREDIT_APPLIED = 1.0
CREDIT_DECLARED = 0.8
CREDIT_RELATED = 0.35


@dataclass
class SkillMatch:
    """One requirement skill, resolved against the resume."""

    skill: str
    category: str
    category_label: str
    importance: float
    tier: str
    priority: str
    status: str  # matched | partial | missing
    credit: float
    evidence: str = ""
    via: str = ""  # the related skill that produced partial credit
    learn_weeks: int = 4
    emerging: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "category": self.category,
            "category_label": self.category_label,
            "importance": round(self.importance, 3),
            "tier": self.tier,
            "priority": self.priority,
            "status": self.status,
            "credit": round(self.credit, 2),
            "evidence": self.evidence,
            "via": self.via,
            "learn_weeks": self.learn_weeks,
            "emerging": self.emerging,
            "reason": self.reason,
        }


@dataclass
class MatchResult:
    requirement: JobRequirement
    matches: list[SkillMatch]
    components: list[ComponentScore]
    keyword_analysis: dict[str, Any]
    experience_analysis: dict[str, Any]
    radar: dict[str, Any]
    extra_skills: list[str] = field(default_factory=list)

    # -- buckets -----------------------------------------------------------

    def matched(self) -> list[SkillMatch]:
        return [m for m in self.matches if m.status == "matched"]

    def partial(self) -> list[SkillMatch]:
        return [m for m in self.matches if m.status == "partial"]

    def missing(self, tiers: tuple[str, ...] = ("required", "preferred")) -> list[SkillMatch]:
        return [m for m in self.matches if m.status == "missing" and m.tier in tiers]

    def missing_by_priority(self, priority: str) -> list[SkillMatch]:
        return [m for m in self.missing(("required", "preferred", "optional")) if m.priority == priority]

    def optional_missing(self) -> list[SkillMatch]:
        return [m for m in self.matches if m.status == "missing" and m.tier == "optional"]

    def emerging_gaps(self) -> list[SkillMatch]:
        return [m for m in self.matches if m.status != "matched" and m.emerging]

    def gap_report(self) -> dict[str, Any]:
        return {
            "matched": [m.to_dict() for m in self.matched()],
            "partially_matched": [m.to_dict() for m in self.partial()],
            "missing_high_priority": [m.to_dict() for m in self.missing_by_priority("high")],
            "missing_medium_priority": [m.to_dict() for m in self.missing_by_priority("medium")],
            "missing_low_priority": [
                m.to_dict() for m in self.missing_by_priority("low") if m.tier != "optional"
            ],
            "optional": [m.to_dict() for m in self.optional_missing()],
            "emerging": [m.to_dict() for m in self.emerging_gaps()],
            "additional_skills": self.extra_skills,
            "counts": {
                "matched": len(self.matched()),
                "partial": len(self.partial()),
                "missing_high": len(self.missing_by_priority("high")),
                "missing_medium": len(self.missing_by_priority("medium")),
                "missing_low": len(
                    [m for m in self.missing_by_priority("low") if m.tier != "optional"]
                ),
                "optional": len(self.optional_missing()),
                "total_requirements": len(self.matches),
            },
        }


class JobMatcher:
    """Resolves a resume against a job requirement profile."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or get_knowledge_base()
        self.extractor = get_skill_extractor()
        self.similarity = get_similarity_model()

    # -- public ------------------------------------------------------------

    def match(
        self,
        resume: ParsedResume,
        skills: list[ExtractedSkill],
        requirement: JobRequirement,
    ) -> MatchResult:
        by_name = {s.name.lower(): s for s in skills}
        matches = [self._resolve(req, by_name) for req in requirement.skills]

        keyword_analysis = self._analyse_keywords(resume, requirement)
        experience_analysis = self._analyse_experience(resume, requirement)
        components = self._score_components(
            resume, skills, requirement, matches, keyword_analysis, experience_analysis
        )
        radar = self._build_radar(matches, requirement)

        required_names = {m.skill.lower() for m in matches}
        extra = [
            s.name
            for s in skills
            if s.name.lower() not in required_names and s.category != "soft"
        ][:20]

        return MatchResult(
            requirement=requirement,
            matches=matches,
            components=components,
            keyword_analysis=keyword_analysis,
            experience_analysis=experience_analysis,
            radar=radar,
            extra_skills=extra,
        )

    # -- resolution --------------------------------------------------------

    def _resolve(self, req, by_name: dict[str, ExtractedSkill]) -> SkillMatch:
        base = SkillMatch(
            skill=req.skill,
            category=req.category or self.kb.category_of(req.skill),
            category_label=self.kb.category_label(req.category or self.kb.category_of(req.skill)),
            importance=req.importance,
            tier=req.tier,
            priority=req.priority,
            status="missing",
            credit=0.0,
            learn_weeks=self.kb.learn_weeks(req.skill),
            emerging=self.kb.is_emerging(req.skill),
        )

        hit = by_name.get(req.skill.lower())
        if hit is not None:
            if hit.applied:
                base.status = "matched"
                base.credit = CREDIT_APPLIED
                base.reason = f"Used in your {', '.join(hit.sections)} section"
            elif hit.declared_only:
                base.status = "partial"
                base.credit = CREDIT_DECLARED
                base.reason = (
                    "Listed in your skills section but not demonstrated in any experience "
                    "or project bullet"
                )
            else:
                base.status = "matched"
                base.credit = CREDIT_DECLARED
                base.reason = f"Mentioned in your {', '.join(hit.sections)} section"
            base.evidence = hit.evidence[0].snippet if hit.evidence else ""
            return base

        # Partial credit through the skill graph: a requirement is partially
        # covered when the resume shows a directly related skill.
        for related in self.kb.related_skills(req.skill):
            related_hit = by_name.get(related.lower())
            if related_hit and related_hit.applied:
                base.status = "partial"
                base.credit = CREDIT_RELATED
                base.via = related_hit.name
                base.reason = (
                    f"Not stated directly, but your {related_hit.name} experience is adjacent - "
                    f"name {req.skill} explicitly if you have genuinely used it"
                )
                base.evidence = related_hit.evidence[0].snippet if related_hit.evidence else ""
                return base

        # Reverse edge: resume skill lists this requirement as related.
        for name, skill in by_name.items():
            if skill.applied and req.skill in self.kb.related_skills(skill.name):
                base.status = "partial"
                base.credit = CREDIT_RELATED
                base.via = skill.name
                base.reason = (
                    f"Your {skill.name} work is adjacent to {req.skill} - make the connection "
                    "explicit if it is genuine"
                )
                base.evidence = skill.evidence[0].snippet if skill.evidence else ""
                return base

        base.reason = f"No evidence of {req.skill} found anywhere in the resume"
        return base

    # -- component scores --------------------------------------------------

    def _score_components(
        self,
        resume: ParsedResume,
        skills: list[ExtractedSkill],
        requirement: JobRequirement,
        matches: list[SkillMatch],
        keyword_analysis: dict[str, Any],
        experience_analysis: dict[str, Any],
    ) -> list[ComponentScore]:
        return [
            self._skills_component(matches),
            self._keyword_component(keyword_analysis),
            self._experience_component(experience_analysis),
            self._projects_component(resume, requirement, matches),
            self._education_component(resume, requirement),
            self._semantic_component(resume, skills, requirement),
        ]

    def _skills_component(self, matches: list[SkillMatch]) -> ComponentScore:
        weighted = [(m.importance, m.credit) for m in matches]
        total = sum(w for w, _ in weighted)
        earned = sum(w * c for w, c in weighted)
        score = clamp_score((earned / total) * 100) if total else 0.0
        req_matches = [m for m in matches if m.tier == "required"]
        req_covered = sum(1 for m in req_matches if m.status == "matched")
        return ComponentScore(
            key="skills",
            score=score,
            detail=(
                f"{req_covered} of {len(req_matches)} required skills fully evidenced; "
                f"score is importance-weighted, so high-priority gaps cost more."
            ),
            evidence={
                "required_total": len(req_matches),
                "required_matched": req_covered,
                "matched": len([m for m in matches if m.status == "matched"]),
                "partial": len([m for m in matches if m.status == "partial"]),
                "missing": len([m for m in matches if m.status == "missing"]),
                "importance_weight_earned": round(earned, 2),
                "importance_weight_available": round(total, 2),
            },
        )

    def _keyword_component(self, analysis: dict[str, Any]) -> ComponentScore:
        coverage = analysis["coverage"]
        return ComponentScore(
            key="keywords",
            score=clamp_score(coverage * 100),
            detail=(
                f"{len(analysis['present'])} of {analysis['total']} target keywords appear in full"
                + (f", {len(analysis['partial'])} partially" if analysis["partial"] else "")
                + ". These are the phrases recruiters and ATS filters search for."
            ),
            evidence={
                "present": analysis["present"][:20],
                "partial": analysis["partial"][:20],
                "missing": analysis["missing"][:20],
                "coverage": round(coverage, 3),
                "scoring": "full match counts 1, partial match counts 0.5",
            },
        )

    def _experience_component(self, analysis: dict[str, Any]) -> ComponentScore:
        return ComponentScore(
            key="experience",
            score=clamp_score(analysis["score"]),
            detail=analysis["detail"],
            evidence={
                "detected_years": analysis["detected_years"],
                "expected_years": analysis["expected_years"],
                "roles_found": analysis["roles_found"],
                "relevance": analysis["relevance"],
                "quantified_bullets": analysis["quantified_bullets"],
                "total_bullets": analysis["total_bullets"],
            },
        )

    def _projects_component(
        self, resume: ParsedResume, requirement: JobRequirement, matches: list[SkillMatch]
    ) -> ComponentScore:
        projects = resume.projects
        if not projects:
            return ComponentScore(
                key="projects",
                score=0.0,
                detail=(
                    "No projects section was detected. For this target, projects are one of the "
                    "few places you can demonstrate missing skills honestly."
                ),
                evidence={"count": 0},
            )

        project_text = "\n".join(p.raw for p in projects)
        project_skills = set(self.extractor.extract_from_text(project_text))
        target_skills = {m.skill for m in matches}
        overlap = project_skills & target_skills
        weighted_overlap = sum(
            m.importance for m in matches if m.skill in overlap
        ) / max(1e-6, sum(m.importance for m in matches))

        depth_bullets = sum(len(p.bullets) for p in projects)
        quantified = sum(1 for p in projects if find_metrics(p.raw))
        depth_ratio = min(1.0, depth_bullets / max(1, len(projects) * 3))
        quantified_ratio = quantified / len(projects)

        score = clamp_score(
            100 * (0.6 * min(1.0, weighted_overlap * 3.0) + 0.25 * depth_ratio + 0.15 * quantified_ratio)
        )
        return ComponentScore(
            key="projects",
            score=score,
            detail=(
                f"{len(projects)} project(s) covering {len(overlap)} of the target's skills, "
                f"{quantified} with a quantified result."
            ),
            evidence={
                "count": len(projects),
                "names": [p.name for p in projects][:8],
                "relevant_skills": sorted(overlap)[:15],
                "quantified_projects": quantified,
                "average_bullets": round(depth_bullets / len(projects), 1),
            },
        )

    def _education_component(
        self, resume: ParsedResume, requirement: JobRequirement
    ) -> ComponentScore:
        education = resume.education
        certifications = resume.certifications
        score = 0.0
        notes: list[str] = []

        if education:
            score += 55
            notes.append(f"{len(education)} education entry(ies) detected")
            degrees = " ".join(e.degree.lower() for e in education)
            fields = " ".join(
                f"{e.field_of_study} {e.raw}".lower() for e in education
            )
            if any(k in degrees for k in ("master", "m.tech", "msc", "phd", "mba", "m.sc")):
                score += 12
                notes.append("postgraduate qualification")
            relevant_terms = ("computer", "software", "data", "information", "electronic",
                              "electrical", "statistic", "mathemat", "artificial", "machine")
            if any(term in fields for term in relevant_terms):
                score += 18
                notes.append("field of study is relevant to the target role")
            else:
                notes.append("field of study is not obviously technical - make the connection explicit")
            if any(e.score for e in education):
                score += 5
        else:
            notes.append("no education section detected")

        if certifications:
            score += min(15, 5 * len(certifications))
            notes.append(f"{len(certifications)} certification line(s)")
        elif requirement.company_id in {"ibm", "microsoft", "amazon"}:
            notes.append(
                f"{requirement.company_name} weights recognised certifications more than most - "
                "a relevant cloud or ML certification would help here"
            )

        return ComponentScore(
            key="education",
            score=clamp_score(score),
            detail="; ".join(notes).capitalize(),
            evidence={
                "entries": [
                    {"degree": e.degree, "institution": e.institution, "year": e.year}
                    for e in education
                ],
                "certifications": certifications[:10],
            },
        )

    def _semantic_component(
        self, resume: ParsedResume, skills: list[ExtractedSkill], requirement: JobRequirement
    ) -> ComponentScore:
        expanded = self.extractor.expand_related(skills)
        result = self.similarity.compare(
            resume.raw_text, requirement.requirement_text(), expanded
        )
        # Raw cosine on short documents rarely exceeds ~0.45, so the raw value is
        # rescaled onto a 0-100 band. The rescaling is reported transparently.
        score = clamp_score(min(1.0, result.semantic / 0.35) * 100)
        return ComponentScore(
            key="semantic",
            score=score,
            detail=(
                f"TF-IDF cosine similarity of {result.tfidf_cosine:.3f} between your resume and "
                f"the target profile (rescaled - resume/JD pairs rarely exceed 0.35)."
            ),
            evidence={
                **result.to_dict(),
                "rescale_divisor": 0.35,
                "expanded_terms": expanded[:15],
            },
        )

    # -- sub-analyses ------------------------------------------------------

    def _analyse_keywords(
        self, resume: ParsedResume, requirement: JobRequirement
    ) -> dict[str, Any]:
        coverage, present, partial, missing = self.similarity.keyword_coverage(
            resume.raw_text, requirement.keywords
        )
        return {
            "coverage": coverage,
            "present": present,
            "partial": partial,
            "missing": missing,
            "total": len(requirement.keywords),
            "note": (
                "Missing keywords are not instructions to insert phrases. Use them only where "
                "they describe work you genuinely did."
            ),
        }

    def _analyse_experience(
        self, resume: ParsedResume, requirement: JobRequirement
    ) -> dict[str, Any]:
        months = resume.total_experience_months
        declared = float(resume.metadata.get("declared_years_experience", 0) or 0)
        detected_years = round(max(months / 12.0, declared), 1)
        expected = requirement.expected_years

        experience_text = resume.sections.get("experience", "") or "\n".join(
            e.raw for e in resume.experience
        )
        relevance = 0.0
        if experience_text.strip():
            relevance = self.similarity.tfidf_cosine(
                experience_text, requirement.requirement_text()
            )

        bullets = [b for e in resume.experience for b in e.bullets] or resume.bullets
        quantified = sum(1 for b in bullets if find_metrics(b))
        quantified_ratio = quantified / len(bullets) if bullets else 0.0

        if expected <= 0:
            duration_score = 100.0 if resume.experience else 55.0
        else:
            duration_score = min(100.0, (detected_years / expected) * 100)

        score = clamp_score(
            0.5 * duration_score
            + 0.3 * min(100.0, (relevance / 0.4) * 100)
            + 0.2 * (quantified_ratio * 100)
        )

        if not resume.experience:
            detail = (
                "No work experience entries were detected. For this level the weight sits mostly "
                "on projects, so make those as concrete as possible."
            )
        elif detected_years < expected:
            detail = (
                f"About {detected_years} year(s) of experience detected against roughly "
                f"{expected} expected for {requirement.level_title.lower()}. "
                f"{quantified} of {len(bullets)} bullets carry a measurable result."
            )
        else:
            detail = (
                f"{detected_years} year(s) detected, at or above the {expected}-year expectation. "
                f"{quantified} of {len(bullets)} bullets carry a measurable result."
            )

        return {
            "score": score,
            "detail": detail,
            "detected_years": detected_years,
            "expected_years": expected,
            "gap_years": round(max(0.0, expected - detected_years), 1),
            "roles_found": [
                {
                    "title": e.title,
                    "organisation": e.organisation,
                    "date_range": e.date_range,
                    "months": e.duration_months,
                }
                for e in resume.experience
            ],
            "relevance": round(relevance, 3),
            "quantified_bullets": quantified,
            "total_bullets": len(bullets),
            "duration_score": round(duration_score, 1),
        }

    # -- radar -------------------------------------------------------------

    def _build_radar(
        self, matches: list[SkillMatch], requirement: JobRequirement
    ) -> dict[str, Any]:
        """Candidate vs target coverage per skill category (radar chart data)."""
        axes: list[dict[str, Any]] = []
        for category in requirement.radar_axes:
            in_axis = [m for m in matches if m.category == category]
            if not in_axis:
                continue
            available = sum(m.importance for m in in_axis)
            earned = sum(m.importance * m.credit for m in in_axis)
            axes.append(
                {
                    "axis": self.kb.category_label(category),
                    "category": category,
                    "candidate": round((earned / available) * 100, 1) if available else 0.0,
                    "target": 100.0,
                    "skills_total": len(in_axis),
                    "skills_matched": len([m for m in in_axis if m.status == "matched"]),
                }
            )
        return {"axes": axes}


_MATCHER: JobMatcher | None = None


def get_job_matcher() -> JobMatcher:
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = JobMatcher()
    return _MATCHER
