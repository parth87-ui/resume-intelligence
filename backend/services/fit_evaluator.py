"""Fit verdict.

The score answers "how well does this resume match?". This answers the question
a candidate actually asks first: **should I apply?**

Those are different questions. A resume can score 62/100 and still be an
automatic rejection because the posting demands a Master's it does not have, or
because it covers only a third of the hard requirements. A weighted average
hides that; a knockout does not. So this module runs a short list of explicit
checks, any one of which can veto the verdict on its own, and reports each one
with its own status and reason.

Every threshold is a named constant at the top of the file. Nothing here
invents credentials: a failing check is always answered with "here is what is
missing", never "say you have it".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.job_matcher import MatchResult
from services.resume_parser import ParsedResume

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

COVERAGE_KNOCKOUT = 0.40
"""Below this share of required skills, nothing else can rescue the verdict."""

STRONG_COVERAGE, STRONG_SCORE = 0.80, 70.0
GOOD_COVERAGE, GOOD_SCORE = 0.65, 55.0
PARTIAL_COVERAGE = 0.40

EXPERIENCE_KNOCKOUT_GAP_YEARS = 2.0
"""Only applied when the posting *states* a number - see _check_experience."""

EXPERIENCE_WARN_GAP_YEARS = 1.0

BLOCKING_GAP_FAIL = 3
"""This many high-priority gaps reads as a fail, fewer as a warning."""

SCORE_PASS, SCORE_WARN = 70.0, 55.0

POSTGRAD_LEVELS = frozenset({"master", "phd"})

VERDICT_STRONG = "Strong fit"
VERDICT_GOOD = "Good fit"
VERDICT_PARTIAL = "Partial fit"
VERDICT_NONE = "Not a fit"

FIT_VERDICTS = frozenset({VERDICT_STRONG, VERDICT_GOOD})

# Degree markers, searched against the resume's own education entries.
_RESUME_DEGREE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("phd", r"\bph\.?\s?d\b|\bdoctor(?:ate|al)\b"),
    ("master", r"\bmaster\b|\bm\.?\s?tech\b|\bm\.?\s?sc\b|\bm\.?s\.?\b|\bmba\b|\bm\.?e\.?\b"),
    ("bachelor", r"\bbachelor\b|\bb\.?\s?tech\b|\bb\.?\s?sc\b|\bb\.?s\.?\b|\bb\.?e\.?\b|\bb\.?c\.?a\b"),
)


@dataclass
class FitCheck:
    key: str
    label: str
    status: str  # pass | warn | fail
    detail: str
    knockout: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "knockout": self.knockout,
        }


@dataclass
class FitAssessment:
    verdict: str
    confidence: float
    headline: str
    checks: list[FitCheck]
    blocking_skills: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    next_step: str = ""
    coverage: float = 0.0

    @property
    def is_fit(self) -> bool:
        return self.verdict in FIT_VERDICTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "is_fit": self.is_fit,
            "confidence": round(self.confidence, 1),
            "headline": self.headline,
            "checks": [c.to_dict() for c in self.checks],
            "blocking_skills": self.blocking_skills,
            "strengths": self.strengths,
            "next_step": self.next_step,
            "required_coverage": round(self.coverage * 100, 1),
            "knockouts": [c.key for c in self.checks if c.knockout],
        }


class FitEvaluator:
    """Turns a match + score into an apply/don't-apply verdict."""

    def evaluate(
        self,
        resume: ParsedResume,
        match: MatchResult,
        report: Any,
        jd_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        required = [m for m in match.matches if m.tier == "required"]
        coverage = self._coverage(required)
        blocking = match.missing_by_priority("high")

        checks = [
            self._check_coverage(required, coverage),
            self._check_blocking(blocking),
            self._check_experience(match, jd_analysis),
            self._check_degree(resume, jd_analysis),
            self._check_score(report),
        ]

        verdict = self._verdict(checks, coverage, report.overall)
        assessment = FitAssessment(
            verdict=verdict,
            confidence=self._confidence(checks, coverage, report.overall, len(required)),
            headline=self._headline(verdict, match, coverage, checks),
            checks=checks,
            blocking_skills=[m.skill for m in blocking],
            strengths=self._strengths(match, report),
            next_step=self._next_step(verdict, match, checks),
            coverage=coverage,
        )
        return assessment.to_dict()

    # -- checks ------------------------------------------------------------

    @staticmethod
    def _coverage(required: list) -> float:
        """Share of required skills evidenced, partials counted at their credit.

        A partial is worth what the matcher already decided it is worth: 0.8 for
        a skill listed but never demonstrated, 0.35 for one inferred from an
        adjacent skill. Re-deciding that here would make two sources of truth.
        """
        if not required:
            return 1.0
        earned = sum(
            1.0 if m.status == "matched" else (m.credit if m.status == "partial" else 0.0)
            for m in required
        )
        return earned / len(required)

    def _check_coverage(self, required: list, coverage: float) -> FitCheck:
        if not required:
            return FitCheck(
                "required_coverage",
                "Required skills",
                "pass",
                "This target lists no hard requirements, so coverage cannot block you.",
            )

        matched = len([m for m in required if m.status == "matched"])
        partial = len([m for m in required if m.status == "partial"])
        detail = (
            f"{coverage * 100:.0f}% of {len(required)} required skills evidenced "
            f"({matched} fully, {partial} partially)."
        )
        if coverage < COVERAGE_KNOCKOUT:
            return FitCheck(
                "required_coverage",
                "Required skills",
                "fail",
                detail + f" Below {COVERAGE_KNOCKOUT * 100:.0f}% this role is out of reach today.",
                knockout=True,
            )
        status = "pass" if coverage >= GOOD_COVERAGE else "warn"
        return FitCheck("required_coverage", "Required skills", status, detail)

    @staticmethod
    def _check_blocking(blocking: list) -> FitCheck:
        if not blocking:
            return FitCheck(
                "blocking_gaps",
                "Blocking gaps",
                "pass",
                "Every high-priority requirement appears somewhere in your resume.",
            )
        names = ", ".join(m.skill for m in blocking[:5])
        status = "fail" if len(blocking) >= BLOCKING_GAP_FAIL else "warn"
        return FitCheck(
            "blocking_gaps",
            "Blocking gaps",
            status,
            f"{len(blocking)} high-priority skill(s) with no evidence: {names}.",
        )

    @staticmethod
    def _check_experience(match: MatchResult, jd_analysis: dict[str, Any] | None) -> FitCheck:
        analysis = match.experience_analysis
        detected = float(analysis.get("detected_years") or 0.0)
        stated = float((jd_analysis or {}).get("years_required") or 0.0)

        if stated > 0:
            # The posting names a number, so the gap is a real filter.
            gap = stated - detected
            detail = f"{detected:g} year(s) detected against the {stated:g} the posting asks for."
            if gap >= EXPERIENCE_KNOCKOUT_GAP_YEARS:
                return FitCheck(
                    "experience",
                    "Experience",
                    "fail",
                    detail + " A gap this size is usually filtered out before a human reads it.",
                    knockout=True,
                )
            if gap >= EXPERIENCE_WARN_GAP_YEARS:
                return FitCheck(
                    "experience",
                    "Experience",
                    "warn",
                    detail + " Worth applying, but lead with depth rather than duration.",
                )
            return FitCheck("experience", "Experience", "pass", detail)

        # No JD number: the level expectation is a guideline, never a knockout,
        # because it came from our own catalogue rather than the employer.
        expected = float(analysis.get("expected_years") or 0.0)
        detail = (
            f"{detected:g} year(s) detected; roughly {expected:g} is typical for "
            f"{match.requirement.level_title.lower()}."
        )
        if expected and detected < expected - EXPERIENCE_WARN_GAP_YEARS:
            return FitCheck(
                "experience",
                "Experience",
                "warn",
                detail + " This posting states no minimum, so it is guidance, not a filter.",
            )
        return FitCheck("experience", "Experience", "pass", detail)

    def _check_degree(
        self, resume: ParsedResume, jd_analysis: dict[str, Any] | None
    ) -> FitCheck:
        required = (jd_analysis or {}).get("degree_required") or {}
        wanted = required.get("level", "none")
        if wanted == "none":
            return FitCheck(
                "degree",
                "Education",
                "pass",
                "No specific degree level is required by this posting.",
            )

        held = self._resume_degree_level(resume)
        field_text = f" in {required['field']}" if required.get("field") else ""
        label = required.get("level_label", wanted.title())

        if wanted in POSTGRAD_LEVELS and held not in POSTGRAD_LEVELS:
            detail = f"This posting requires a {label}{field_text}; none is detected in your resume."
            if required.get("equivalent_allowed"):
                detail += " It does accept equivalent experience, so this is worth a closer read."
            return FitCheck("degree", "Education", "fail", detail, knockout=True)

        if wanted == "bachelor" and not resume.education:
            return FitCheck(
                "degree",
                "Education",
                "warn",
                f"A {label}{field_text} is required and no education section was detected. "
                "If you hold one, add it - it is being missed, not absent.",
            )

        return FitCheck(
            "degree",
            "Education",
            "pass",
            f"Your education meets the {label}{field_text} requirement.",
        )

    @staticmethod
    def _check_score(report: Any) -> FitCheck:
        score = float(report.overall)
        detail = f"Overall match {score:.0f}/100 ({report.band})."
        if score >= SCORE_PASS:
            return FitCheck("overall_score", "Overall match", "pass", detail)
        if score >= SCORE_WARN:
            return FitCheck("overall_score", "Overall match", "warn", detail)
        return FitCheck("overall_score", "Overall match", "fail", detail)

    # -- verdict -----------------------------------------------------------

    @staticmethod
    def _verdict(checks: list[FitCheck], coverage: float, score: float) -> str:
        if any(c.knockout for c in checks):
            return VERDICT_NONE
        if coverage >= STRONG_COVERAGE and score >= STRONG_SCORE:
            return VERDICT_STRONG
        if coverage >= GOOD_COVERAGE and score >= GOOD_SCORE:
            return VERDICT_GOOD
        if coverage >= PARTIAL_COVERAGE:
            return VERDICT_PARTIAL
        return VERDICT_NONE

    @staticmethod
    def _confidence(
        checks: list[FitCheck], coverage: float, score: float, required_count: int
    ) -> float:
        """How certain the verdict is - distance from the boundary, not a probability."""
        knockouts = [c for c in checks if c.knockout]
        if knockouts:
            return min(100.0, 82.0 + 6.0 * len(knockouts))

        nearest = min(
            abs(coverage - boundary)
            for boundary in (PARTIAL_COVERAGE, GOOD_COVERAGE, STRONG_COVERAGE)
        )
        # More requirements to judge against = a more reliable read.
        evidence = min(1.0, required_count / 8.0)
        margin = min(1.0, nearest / 0.20)
        return min(97.0, 50.0 + 37.0 * margin + 10.0 * evidence)

    @staticmethod
    def _target_phrase(match: MatchResult) -> str:
        """How to name the target in prose.

        A pasted posting with no detectable employer carries the placeholder
        company name "Pasted job description", which reads badly mid-sentence.
        """
        role = match.requirement.role_title
        company = match.requirement.company_name
        if not company or company.lower().startswith("pasted"):
            return f"{role} role"
        return f"{role} at {company}"

    @staticmethod
    def _headline(verdict: str, match: MatchResult, coverage: float, checks: list[FitCheck]) -> str:
        target = FitEvaluator._target_phrase(match)
        knockout = next((c for c in checks if c.knockout), None)
        if knockout is not None:
            return f"Not worth applying to this {target} yet - {knockout.label.lower()} rules you out."
        if verdict == VERDICT_STRONG:
            return f"You are a strong candidate for this {target}. Apply."
        if verdict == VERDICT_GOOD:
            return f"Worth applying to this {target}, with the gaps below addressed first."
        return (
            f"You cover {coverage * 100:.0f}% of what this {target} requires - "
            "a real gap, but a closable one."
        )

    @staticmethod
    def _strengths(match: MatchResult, report: Any) -> list[str]:
        strengths = [
            m.skill for m in match.matches if m.tier == "required" and m.status == "matched"
        ][:6]
        for component in report.components:
            if component.score >= SCORE_PASS:
                strengths.append(f"{component.label} {component.score:.0f}/100")
        return strengths[:8]

    @staticmethod
    def _next_step(verdict: str, match: MatchResult, checks: list[FitCheck]) -> str:
        # A knockout is the only thing worth talking about: polishing wording
        # while a hard filter excludes you is wasted effort.
        knockout = next((c for c in checks if c.knockout), None)
        if knockout is not None:
            return {
                "required_coverage": (
                    "Too much of this role is missing to fix by rewriting. Use the roadmap to "
                    "close the high-priority gaps, then re-run this analysis."
                ),
                "experience": (
                    "This posting's experience bar is the blocker, and that is not something a "
                    "resume edit can close. Target roles at your level, where your depth counts "
                    "for more than your years."
                ),
                "degree": (
                    "The degree requirement is the blocker. If you hold the qualification, make "
                    "sure it is stated plainly in an education section - it may simply be missed. "
                    "If not, look for postings that accept equivalent experience."
                ),
            }.get(knockout.key, "Close the blocking requirement before applying.")

        hidden = [m for m in match.partial() if not m.via]
        if verdict == VERDICT_STRONG:
            return (
                "Tailor the wording to this posting's vocabulary and apply. "
                "Nothing needs to be learned first."
            )
        if hidden:
            names = ", ".join(m.skill for m in hidden[:3])
            return (
                f"Quickest win: {names} sit in your skills list but are never demonstrated. "
                "Move them into a real bullet - that raises your score without learning anything new."
            )
        blocking = match.missing_by_priority("high")
        if blocking:
            names = ", ".join(m.skill for m in blocking[:3])
            return (
                f"Close {names} before applying. The project recommendations show a route to "
                "each one - add them to the resume only once you have finished them."
            )
        return "Strengthen the evidence you already have: measurable results and specific tools."

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _resume_degree_level(resume: ParsedResume) -> str:
        blob = " ".join(
            f"{e.degree} {e.field_of_study} {e.raw}" for e in resume.education
        ).lower()
        if not blob.strip():
            blob = (resume.sections.get("education") or "").lower()
        for level, pattern in _RESUME_DEGREE_PATTERNS:
            if re.search(pattern, blob):
                return level
        return "none" if not resume.education else "unspecified"


_EVALUATOR: FitEvaluator | None = None


def get_fit_evaluator() -> FitEvaluator:
    global _EVALUATOR
    if _EVALUATOR is None:
        _EVALUATOR = FitEvaluator()
    return _EVALUATOR
