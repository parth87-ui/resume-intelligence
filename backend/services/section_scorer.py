"""Per-section resume scoring.

The weighted match score says *which scoring dimension* is weak. This says
*which part of the document* is weak, which is what you actually edit. The two
are deliberately different views of the same evidence.

Each section is scored 0-100 from a fixed list of checks, and every check
returns its own verdict and reason, so the number is never a black box:

    summary     presence, length, specificity, target alignment
    skills      presence, breadth, grouping, evidence, requirement coverage
    experience  presence, dating, depth, action verbs, metrics, relevance
    projects    presence, depth, named stack, metrics, links, relevance
    education   presence, degree, dates, field relevance, certifications
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ml.nlp_pipeline import ACTION_VERBS, WEAK_OPENERS, find_metrics
from services.job_matcher import MatchResult
from services.resume_parser import ParsedResume

GENERIC_PHRASES = (
    "hard working", "hardworking", "team player", "passionate", "quick learner",
    "detail oriented", "detail-oriented", "highly motivated", "self motivated",
    "go-getter", "think outside the box", "results driven", "dynamic professional",
)

LINK_RE = re.compile(r"https?://|github\.com|gitlab\.com|\bdemo\b|\blive\b", re.I)
TECH_RE = re.compile(r"\b(using|built with|tech(?:nologies)?|stack|tools)\b", re.I)


@dataclass
class SectionCheck:
    label: str
    status: str  # pass | warn | fail
    points: float
    max_points: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "points": round(self.points, 1),
            "max_points": self.max_points,
            "detail": self.detail,
        }


@dataclass
class SectionScore:
    key: str
    label: str
    present: bool
    checks: list[SectionCheck]

    @property
    def score(self) -> float:
        available = sum(c.max_points for c in self.checks)
        earned = sum(c.points for c in self.checks)
        return round((earned / available) * 100, 1) if available else 0.0

    @property
    def verdict(self) -> str:
        score = self.score
        if not self.present:
            return "missing"
        if score >= 80:
            return "strong"
        if score >= 55:
            return "adequate"
        return "weak"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "score": self.score,
            "present": self.present,
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
            "weakest": next(
                (c.label for c in sorted(self.checks, key=lambda c: c.points / c.max_points)
                 if c.status != "pass"),
                "",
            ),
        }


def _check(label: str, ratio: float, max_points: float, detail: str) -> SectionCheck:
    """A check scored on a 0-1 ratio, with the status derived from it."""
    ratio = max(0.0, min(1.0, ratio))
    status = "pass" if ratio >= 0.8 else ("warn" if ratio >= 0.4 else "fail")
    return SectionCheck(label, status, ratio * max_points, max_points, detail)


class SectionScorer:
    """Scores each resume section against the selected target."""

    def score(self, resume: ParsedResume, match: MatchResult) -> dict[str, Any]:
        sections = [
            self._summary(resume, match),
            self._skills(resume, match),
            self._experience(resume, match),
            self._projects(resume, match),
            self._education(resume, match),
        ]
        scored = [s.to_dict() for s in sections]
        overall = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else 0.0
        weakest = min(scored, key=lambda s: s["score"])

        return {
            "overall": overall,
            "sections": scored,
            "weakest_section": weakest["key"],
            "summary": (
                f"Your {weakest['label'].lower()} section is the weakest at "
                f"{weakest['score']:.0f}/100"
                + (f" - {weakest['weakest'].lower()}." if weakest["weakest"] else ".")
            ),
            "note": (
                "Section scores show which part of the document to edit. They are computed "
                "from the same evidence as the match score, viewed by document structure "
                "rather than by scoring dimension."
            ),
        }

    # -- sections ----------------------------------------------------------

    def _summary(self, resume: ParsedResume, match: MatchResult) -> SectionScore:
        text = (resume.sections.get("summary") or "").strip()
        checks: list[SectionCheck] = []

        checks.append(
            _check(
                "Section present", 1.0 if text else 0.0, 25,
                "Professional summary detected." if text
                else "No summary section - this is the first thing a recruiter reads.",
            )
        )

        words = len(text.split())
        if text:
            ratio = 1.0 if 20 <= words <= 70 else (0.5 if words <= 110 else 0.25)
            checks.append(_check("Length", ratio, 20, f"{words} words (aim for 25-60)."))
        else:
            checks.append(_check("Length", 0.0, 20, "Nothing to measure."))

        generic = [p for p in GENERIC_PHRASES if p in text.lower()]
        checks.append(
            _check(
                "Specific, not generic", 0.0 if generic else (1.0 if text else 0.0), 25,
                f"Contains generic filler: {', '.join(generic[:3])}." if generic
                else ("No generic filler phrases." if text else "Nothing to measure."),
            )
        )

        keywords = [k for k in match.requirement.keywords[:8] if k.lower() in text.lower()]
        role_named = match.requirement.role_title.lower() in text.lower()
        alignment = min(1.0, (len(keywords) / 2) + (0.5 if role_named else 0.0)) if text else 0.0
        checks.append(
            _check(
                "Aligned to the target", alignment, 30,
                f"Mentions {len(keywords)} target keyword(s)"
                + (" and names the role." if role_named else ".") if text
                else "Nothing to measure.",
            )
        )
        return SectionScore("summary", "Professional Summary", bool(text), checks)

    def _skills(self, resume: ParsedResume, match: MatchResult) -> SectionScore:
        block = (resume.sections.get("skills") or "").strip()
        terms = resume.skill_section_terms
        checks: list[SectionCheck] = []

        checks.append(
            _check(
                "Section present", 1.0 if block else 0.0, 20,
                f"Skills section with {len(terms)} listed term(s)." if block
                else "No skills section - ATS parsers look for one explicitly.",
            )
        )

        breadth = min(1.0, len(terms) / 12) if terms else 0.0
        checks.append(
            _check("Breadth", breadth, 15, f"{len(terms)} skills listed (12+ is typical).")
        )

        grouped = ":" in block or block.count("\n") >= 3
        checks.append(
            _check(
                "Grouped by category", 1.0 if grouped else 0.0, 15,
                "Skills are grouped under labels." if grouped
                else "One undifferentiated block - group as Languages / ML / Cloud / Tools.",
            )
        )

        declared_only = [m for m in match.partial() if not m.via]
        required = [m for m in match.matches if m.tier == "required"]
        evidence_ratio = (
            1.0 - min(1.0, len(declared_only) / max(1, len(required)))
        )
        checks.append(
            _check(
                "Backed by evidence", evidence_ratio, 25,
                f"{len(declared_only)} listed skill(s) appear in no bullet: "
                + ", ".join(m.skill for m in declared_only[:4]) if declared_only
                else "Listed skills are demonstrated elsewhere in the resume.",
            )
        )

        matched_required = len([m for m in required if m.status == "matched"])
        coverage = matched_required / len(required) if required else 0.0
        checks.append(
            _check(
                "Covers the target", coverage, 25,
                f"{matched_required} of {len(required)} required skills evidenced for "
                f"{match.requirement.company_name} {match.requirement.role_title}.",
            )
        )
        return SectionScore("skills", "Skills", bool(block), checks)

    def _experience(self, resume: ParsedResume, match: MatchResult) -> SectionScore:
        entries = resume.experience
        bullets = [b for e in entries for b in e.bullets]
        checks: list[SectionCheck] = []

        checks.append(
            _check(
                "Section present", 1.0 if entries else 0.0, 20,
                f"{len(entries)} experience entry(ies) detected." if entries
                else "No work experience entries detected.",
            )
        )

        dated = len([e for e in entries if e.date_range])
        checks.append(
            _check(
                "Dated entries", dated / len(entries) if entries else 0.0, 15,
                f"{dated} of {len(entries)} entries have a parseable date range." if entries
                else "Nothing to measure.",
            )
        )

        depth = min(1.0, len(bullets) / max(1, len(entries) * 3)) if entries else 0.0
        checks.append(
            _check(
                "Depth per role", depth, 15,
                f"{len(bullets)} bullets across {len(entries)} role(s) - 3-5 each is typical."
                if entries else "Nothing to measure.",
            )
        )

        strong = len([b for b in bullets if _first_word(b) in ACTION_VERBS])
        weak = len([b for b in bullets if _first_word(b) in WEAK_OPENERS])
        checks.append(
            _check(
                "Strong action verbs", strong / len(bullets) if bullets else 0.0, 20,
                f"{strong} of {len(bullets)} bullets open with a strong verb"
                + (f"; {weak} open weakly." if weak else ".") if bullets
                else "Nothing to measure.",
            )
        )

        quantified = len([b for b in bullets if find_metrics(b)])
        checks.append(
            _check(
                "Quantified results", (quantified / len(bullets)) / 0.5 if bullets else 0.0, 20,
                f"{quantified} of {len(bullets)} bullets carry a measurable result "
                "(half or more is the goal)." if bullets else "Nothing to measure.",
            )
        )

        relevance = match.experience_analysis["relevance"]
        checks.append(
            _check(
                "Relevant to the target", relevance / 0.35, 10,
                f"Cosine relevance {relevance:.2f} against the "
                f"{match.requirement.role_title} profile.",
            )
        )
        return SectionScore("experience", "Work Experience", bool(entries), checks)

    def _projects(self, resume: ParsedResume, match: MatchResult) -> SectionScore:
        projects = resume.projects
        checks: list[SectionCheck] = []

        checks.append(
            _check(
                "Section present", 1.0 if projects else 0.0, 25,
                f"{len(projects)} project(s) detected." if projects
                else "No projects section - the main place to evidence newly-built skills.",
            )
        )

        count_ratio = min(1.0, len(projects) / 2) if projects else 0.0
        checks.append(
            _check("Enough projects", count_ratio, 10, f"{len(projects)} listed (2-4 is typical).")
        )

        depth = (
            min(1.0, sum(len(p.bullets) for p in projects) / max(1, len(projects) * 3))
            if projects else 0.0
        )
        checks.append(
            _check(
                "Depth", depth, 15,
                f"{sum(len(p.bullets) for p in projects)} bullets across {len(projects)} project(s)."
                if projects else "Nothing to measure.",
            )
        )

        with_tech = len([p for p in projects if p.tech_hint or TECH_RE.search(p.raw)])
        checks.append(
            _check(
                "Technology stack named", with_tech / len(projects) if projects else 0.0, 20,
                f"{with_tech} of {len(projects)} name the tools used." if projects
                else "Nothing to measure.",
            )
        )

        quantified = len([p for p in projects if find_metrics(p.raw)])
        checks.append(
            _check(
                "Measured outcomes", quantified / len(projects) if projects else 0.0, 20,
                f"{quantified} of {len(projects)} state a measurable result." if projects
                else "Nothing to measure.",
            )
        )

        linked = len([p for p in projects if LINK_RE.search(p.raw)])
        checks.append(
            _check(
                "Repository or demo link", linked / len(projects) if projects else 0.0, 10,
                f"{linked} of {len(projects)} link to code or a demo." if projects
                else "Nothing to measure.",
            )
        )
        return SectionScore("projects", "Projects", bool(projects), checks)

    def _education(self, resume: ParsedResume, match: MatchResult) -> SectionScore:
        entries = resume.education
        checks: list[SectionCheck] = []

        checks.append(
            _check(
                "Section present", 1.0 if entries else 0.0, 30,
                f"{len(entries)} education entry(ies) detected." if entries
                else "No education section detected.",
            )
        )

        with_degree = len([e for e in entries if e.degree])
        checks.append(
            _check(
                "Degree parseable", with_degree / len(entries) if entries else 0.0, 20,
                f"{with_degree} of {len(entries)} entries have a recognisable degree."
                if entries else "Nothing to measure.",
            )
        )

        with_year = len([e for e in entries if e.year])
        checks.append(
            _check(
                "Dated", with_year / len(entries) if entries else 0.0, 15,
                f"{with_year} of {len(entries)} entries state a year." if entries
                else "Nothing to measure.",
            )
        )

        relevant_terms = ("computer", "software", "data", "information", "electronic",
                          "electrical", "statistic", "mathemat", "artificial", "machine")
        blob = " ".join(f"{e.field_of_study} {e.raw}".lower() for e in entries)
        relevant = any(term in blob for term in relevant_terms)
        checks.append(
            _check(
                "Field relevance", 1.0 if relevant else 0.0, 20,
                "Field of study is relevant to the target role." if relevant
                else "Field of study is not obviously technical - make the link explicit.",
            )
        )

        certifications = resume.certifications
        checks.append(
            _check(
                "Certifications", min(1.0, len(certifications) / 2), 15,
                f"{len(certifications)} certification line(s) listed." if certifications
                else "No certifications listed.",
            )
        )
        return SectionScore("education", "Education", bool(entries), checks)


def _first_word(text: str) -> str:
    match = re.search(r"[A-Za-z]+", text or "")
    return match.group(0).lower() if match else ""


_SCORER: SectionScorer | None = None


def get_section_scorer() -> SectionScorer:
    global _SCORER
    if _SCORER is None:
        _SCORER = SectionScorer()
    return _SCORER
