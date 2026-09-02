"""ATS (Applicant Tracking System) compatibility analysis.

Runs a fixed battery of checks against the parsed resume, each worth a defined
number of points, and returns a 0-100 score with the full check list so the
user can see exactly why they lost points.

Check families:
    parsability  - can a machine read the file at all
    structure    - standard headings, contact block, length
    content      - action verbs, quantified results, bullet hygiene
    keywords     - target keyword coverage, over-stuffing, skill placement
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ml.nlp_pipeline import ACTION_VERBS, WEAK_OPENERS, find_metrics
from services.job_matcher import MatchResult
from services.resume_parser import ParsedResume

PRONOUN_RE = re.compile(r"\b(I|me|my|mine|myself)\b")
NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")


@dataclass
class ATSCheck:
    id: str
    family: str
    label: str
    status: str  # pass | warn | fail
    points: float
    max_points: float
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "label": self.label,
            "status": self.status,
            "points": round(self.points, 1),
            "max_points": self.max_points,
            "message": self.message,
            "suggestion": self.suggestion,
        }


class ATSAnalyzer:
    """Deterministic ATS scoring - every point is traceable to a check."""

    def analyse(
        self, resume: ParsedResume, match: MatchResult | None = None
    ) -> dict[str, Any]:
        checks: list[ATSCheck] = []
        checks.extend(self._parsability_checks(resume))
        checks.extend(self._structure_checks(resume))
        checks.extend(self._content_checks(resume))
        checks.extend(self._keyword_checks(resume, match))

        earned = sum(c.points for c in checks)
        available = sum(c.max_points for c in checks)
        score = round((earned / available) * 100, 1) if available else 0.0

        by_family: dict[str, dict[str, float]] = {}
        for check in checks:
            bucket = by_family.setdefault(check.family, {"points": 0.0, "max": 0.0})
            bucket["points"] += check.points
            bucket["max"] += check.max_points

        failures = [c for c in checks if c.status == "fail"]
        warnings = [c for c in checks if c.status == "warn"]

        return {
            "score": score,
            "band": _band(score),
            "checks": [c.to_dict() for c in checks],
            "family_scores": {
                family: {
                    "score": round((v["points"] / v["max"]) * 100, 1) if v["max"] else 0.0,
                    "points": round(v["points"], 1),
                    "max_points": round(v["max"], 1),
                    "label": _FAMILY_LABELS.get(family, family.title()),
                }
                for family, v in by_family.items()
            },
            "critical_issues": [c.to_dict() for c in failures],
            "warnings": [c.to_dict() for c in warnings],
            "formatting_warnings": resume.metadata.get("warnings", []),
            "summary": _summarise(score, failures, warnings),
        }

    # -- parsability -------------------------------------------------------

    def _parsability_checks(self, resume: ParsedResume) -> list[ATSCheck]:
        checks: list[ATSCheck] = []
        meta = resume.metadata
        layout_warnings = [
            w for w in meta.get("warnings", []) if "column" in w.lower() or "table" in w.lower()
        ]
        image_warnings = [w for w in meta.get("warnings", []) if "image" in w.lower()]

        checks.append(
            ATSCheck(
                id="text_extractable",
                family="parsability",
                label="Machine-readable text",
                status="pass" if meta.get("words", 0) > 120 else "fail",
                points=10.0 if meta.get("words", 0) > 120 else 0.0,
                max_points=10.0,
                message=f"{meta.get('words', 0)} words extracted using {meta.get('extractor', 'n/a')}.",
                suggestion=""
                if meta.get("words", 0) > 120
                else "Very little text was extracted. Export a text-based PDF rather than a scan or image.",
            )
        )
        checks.append(
            ATSCheck(
                id="simple_layout",
                family="parsability",
                label="Single-column, table-free layout",
                status="warn" if layout_warnings else "pass",
                points=3.0 if layout_warnings else 8.0,
                max_points=8.0,
                message=layout_warnings[0] if layout_warnings else "Layout looks linear and parser-friendly.",
                suggestion="Move content out of tables and columns into plain paragraphs."
                if layout_warnings
                else "",
            )
        )
        checks.append(
            ATSCheck(
                id="no_image_text",
                family="parsability",
                label="No text trapped in images",
                status="warn" if image_warnings else "pass",
                points=2.0 if image_warnings else 5.0,
                max_points=5.0,
                message=image_warnings[0] if image_warnings else "No embedded images detected in the text layer.",
                suggestion="Replace any graphical skill bars or logos with plain text."
                if image_warnings
                else "",
            )
        )
        non_ascii = len(NON_ASCII_RE.findall(resume.raw_text))
        checks.append(
            ATSCheck(
                id="character_set",
                family="parsability",
                label="Standard characters",
                status="pass" if non_ascii < 25 else "warn",
                points=4.0 if non_ascii < 25 else 1.5,
                max_points=4.0,
                message=f"{non_ascii} non-standard characters found.",
                suggestion="Replace decorative symbols, icons and fancy bullets with plain hyphens."
                if non_ascii >= 25
                else "",
            )
        )
        return checks

    # -- structure ---------------------------------------------------------

    def _structure_checks(self, resume: ParsedResume) -> list[ATSCheck]:
        checks: list[ATSCheck] = []
        contact = resume.contact
        present = [k for k in ("email", "phone", "linkedin") if contact.get(k)]
        checks.append(
            ATSCheck(
                id="contact_block",
                family="structure",
                label="Contact details",
                status="pass" if len(present) >= 2 else "fail",
                points=4.0 * len(present) / 3 * 3 if len(present) >= 2 else 2.0,
                max_points=12.0,
                message=f"Found: {', '.join(present) if present else 'nothing usable'}."
                + (f" Name parsed as '{contact.get('name')}'." if contact.get("name") else ""),
                suggestion="Add a plain-text email, phone number and LinkedIn URL at the top."
                if len(present) < 3
                else "",
            )
        )

        expected_sections = ["skills", "experience", "education", "projects"]
        found = [s for s in expected_sections if resume.sections.get(s)]
        checks.append(
            ATSCheck(
                id="standard_headings",
                family="structure",
                label="Standard section headings",
                status="pass" if len(found) >= 3 else ("warn" if len(found) == 2 else "fail"),
                points=12.0 * (len(found) / len(expected_sections)),
                max_points=12.0,
                message=f"Detected {', '.join(found) if found else 'no standard headings'}.",
                suggestion=(
                    "Use conventional headings - Skills, Experience, Projects, Education. "
                    "Creative headings such as 'What I Bring' are frequently skipped by parsers."
                )
                if len(found) < len(expected_sections)
                else "",
            )
        )

        words = resume.metadata.get("words", 0)
        if 380 <= words <= 950:
            status, points, msg = "pass", 8.0, f"{words} words - a good length for one to two pages."
            suggestion = ""
        elif words < 380:
            status, points = "warn", 4.0
            msg = f"{words} words - thin for a technical resume."
            suggestion = "Expand your strongest project and experience bullets with specifics."
        else:
            status, points = "warn", 4.5
            msg = f"{words} words - long enough that reviewers will skim."
            suggestion = "Cut older or less relevant content; keep the most relevant work first."
        checks.append(
            ATSCheck(
                id="length", family="structure", label="Resume length",
                status=status, points=points, max_points=8.0, message=msg, suggestion=suggestion,
            )
        )

        dated = sum(1 for e in resume.experience if e.date_range)
        total_exp = len(resume.experience)
        checks.append(
            ATSCheck(
                id="dates",
                family="structure",
                label="Dated experience entries",
                status="pass" if total_exp == 0 or dated == total_exp else "warn",
                points=6.0 if total_exp == 0 or dated == total_exp else 6.0 * (dated / max(1, total_exp)),
                max_points=6.0,
                message=(
                    f"{dated} of {total_exp} experience entries have a parseable date range."
                    if total_exp
                    else "No work experience entries to date-check."
                ),
                suggestion="Use a consistent 'Mon YYYY - Mon YYYY' format on every role."
                if total_exp and dated < total_exp
                else "",
            )
        )
        return checks

    # -- content -----------------------------------------------------------

    def _content_checks(self, resume: ParsedResume) -> list[ATSCheck]:
        checks: list[ATSCheck] = []
        bullets = resume.bullets

        if not bullets:
            checks.append(
                ATSCheck(
                    id="bullets", family="content", label="Bullet structure",
                    status="fail", points=0.0, max_points=8.0,
                    message="No bullet points detected - the resume reads as prose blocks.",
                    suggestion="Convert responsibilities into 3-6 bullets per role, one achievement each.",
                )
            )
        else:
            long_bullets = [b for b in bullets if len(b.split()) > 34]
            ratio = 1 - (len(long_bullets) / len(bullets))
            checks.append(
                ATSCheck(
                    id="bullets", family="content", label="Bullet structure",
                    status="pass" if ratio > 0.8 else "warn",
                    points=8.0 * ratio, max_points=8.0,
                    message=f"{len(bullets)} bullets, {len(long_bullets)} longer than 34 words.",
                    suggestion="Split long bullets - one accomplishment per line reads better and parses better."
                    if long_bullets
                    else "",
                )
            )

        strong = [b for b in bullets if _first_word(b) in ACTION_VERBS]
        weak = [b for b in bullets if _first_word(b) in WEAK_OPENERS]
        strong_ratio = len(strong) / len(bullets) if bullets else 0.0
        checks.append(
            ATSCheck(
                id="action_verbs", family="content", label="Strong action verbs",
                status="pass" if strong_ratio >= 0.6 else ("warn" if strong_ratio >= 0.3 else "fail"),
                points=10.0 * min(1.0, strong_ratio / 0.7), max_points=10.0,
                message=f"{len(strong)} of {len(bullets)} bullets open with a strong action verb"
                + (f"; {len(weak)} open with a weak verb such as '{_first_word(weak[0])}'." if weak else "."),
                suggestion="Replace 'worked on', 'helped with' and 'responsible for' with verbs like "
                "built, designed, deployed, reduced, led."
                if strong_ratio < 0.6
                else "",
            )
        )

        quantified = [b for b in bullets if find_metrics(b)]
        q_ratio = len(quantified) / len(bullets) if bullets else 0.0
        checks.append(
            ATSCheck(
                id="quantified", family="content", label="Quantified results",
                status="pass" if q_ratio >= 0.4 else ("warn" if q_ratio >= 0.2 else "fail"),
                points=12.0 * min(1.0, q_ratio / 0.5), max_points=12.0,
                message=f"{len(quantified)} of {len(bullets)} bullets contain a number.",
                suggestion=(
                    "Add real measurements you can defend - dataset size, latency, accuracy, "
                    "users, time saved. Never invent a number you cannot support."
                )
                if q_ratio < 0.4
                else "",
            )
        )

        pronouns = len(PRONOUN_RE.findall(resume.raw_text))
        checks.append(
            ATSCheck(
                id="pronouns", family="content", label="Third-person voice",
                status="pass" if pronouns <= 3 else "warn",
                points=4.0 if pronouns <= 3 else 1.5, max_points=4.0,
                message=f"{pronouns} first-person pronoun(s) found.",
                suggestion="Drop 'I' and 'my' - resume bullets conventionally start with the verb."
                if pronouns > 3
                else "",
            )
        )
        return checks

    # -- keywords ----------------------------------------------------------

    def _keyword_checks(
        self, resume: ParsedResume, match: MatchResult | None
    ) -> list[ATSCheck]:
        checks: list[ATSCheck] = []

        if match is None:
            checks.append(
                ATSCheck(
                    id="keyword_coverage", family="keywords", label="Target keyword coverage",
                    status="warn", points=6.0, max_points=12.0,
                    message="No target selected - keyword coverage was not evaluated.",
                    suggestion="Select a target company and role for keyword-level analysis.",
                )
            )
            return checks

        analysis = match.keyword_analysis
        coverage = analysis["coverage"]
        checks.append(
            ATSCheck(
                id="keyword_coverage", family="keywords", label="Target keyword coverage",
                status="pass" if coverage >= 0.5 else ("warn" if coverage >= 0.25 else "fail"),
                points=12.0 * min(1.0, coverage / 0.6), max_points=12.0,
                message=(
                    f"{len(analysis['present'])} of {analysis['total']} "
                    f"{match.requirement.company_name} / {match.requirement.role_title} keywords fully present"
                    + (f", {len(analysis['partial'])} partially." if analysis.get("partial") else ".")
                ),
                suggestion=(
                    "Where these describe work you genuinely did, use the target's own vocabulary: "
                    + ", ".join(analysis["missing"][:4])
                )
                if coverage < 0.5
                else "",
            )
        )

        high_gaps = match.missing_by_priority("high")
        checks.append(
            ATSCheck(
                id="required_skill_terms", family="keywords", label="Required skills present in text",
                status="pass" if not high_gaps else ("warn" if len(high_gaps) <= 2 else "fail"),
                points=max(0.0, 10.0 - 2.5 * len(high_gaps)), max_points=10.0,
                message=(
                    "All high-priority required skills appear in the resume."
                    if not high_gaps
                    else f"{len(high_gaps)} high-priority requirement(s) absent: "
                    + ", ".join(m.skill for m in high_gaps[:5])
                ),
                suggestion=(
                    "Only add these once you genuinely have them - the project recommendations "
                    "below are the honest route to closing these gaps."
                )
                if high_gaps
                else "",
            )
        )

        declared_only = [m for m in match.partial() if not m.via]
        checks.append(
            ATSCheck(
                id="skill_placement", family="keywords", label="Skill placement",
                status="pass" if len(declared_only) <= 2 else "warn",
                points=max(2.0, 8.0 - 1.5 * len(declared_only)), max_points=8.0,
                message=(
                    f"{len(declared_only)} skill(s) appear only in your skills list with no "
                    "supporting bullet."
                    if declared_only
                    else "Listed skills are backed by experience or project evidence."
                ),
                suggestion=(
                    "Reviewers discount skills that appear in no bullet. Add one line of real "
                    "context for: " + ", ".join(m.skill for m in declared_only[:5])
                )
                if declared_only
                else "",
            )
        )

        words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z+#.]{2,}", resume.raw_text)]
        counts = Counter(words)
        total_words = max(1, len(words))
        stuffed = [
            (w, c) for w, c in counts.most_common(40)
            if c >= 9 and c / total_words > 0.012 and w not in {"and", "the", "with", "for", "data"}
        ]
        checks.append(
            ATSCheck(
                id="keyword_stuffing", family="keywords", label="No keyword stuffing",
                status="pass" if not stuffed else "warn",
                points=6.0 if not stuffed else 3.0, max_points=6.0,
                message=(
                    "No unnatural keyword repetition detected."
                    if not stuffed
                    else "Heavily repeated terms: "
                    + ", ".join(f"{w} ({c}x)" for w, c in stuffed[:4])
                ),
                suggestion="Vary phrasing - modern parsers score semantic relevance, and human "
                "reviewers notice repetition."
                if stuffed
                else "",
            )
        )
        return checks


_FAMILY_LABELS = {
    "parsability": "Parsability",
    "structure": "Structure",
    "content": "Content Quality",
    "keywords": "Keyword Alignment",
}


def _band(score: float) -> str:
    if score >= 85:
        return "ATS Ready"
    if score >= 70:
        return "Mostly Compatible"
    if score >= 55:
        return "Needs Work"
    return "High Risk of Rejection"


def _summarise(score: float, failures: list[ATSCheck], warnings: list[ATSCheck]) -> str:
    if not failures and not warnings:
        return f"ATS score {score:.0f}/100 - the resume passed every automated check."
    parts = [f"ATS score {score:.0f}/100."]
    if failures:
        parts.append(
            "Fix first: " + "; ".join(f.label.lower() for f in failures[:3]) + "."
        )
    if warnings:
        parts.append(
            "Then improve: " + "; ".join(w.label.lower() for w in warnings[:3]) + "."
        )
    return " ".join(parts)


def _first_word(text: str) -> str:
    match = re.search(r"[A-Za-z]+", text or "")
    return match.group(0).lower() if match else ""


_ANALYZER: ATSAnalyzer | None = None


def get_ats_analyzer() -> ATSAnalyzer:
    global _ANALYZER
    if _ANALYZER is None:
        _ANALYZER = ATSAnalyzer()
    return _ANALYZER
