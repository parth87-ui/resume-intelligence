"""Skill extraction.

Scans a parsed resume for every skill in the ontology and records *where* each
one was found, because location changes meaning:

    declared  - listed in the skills section only
    applied   - used inside an experience or project bullet (stronger evidence)

Ambiguous short names (C, R, Go, C#) get stricter, case-sensitive patterns so
"go to market" or "R&D" never register as programming languages.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ml.nlp_pipeline import find_metrics, get_pipeline
from services.knowledge_base import KnowledgeBase, get_knowledge_base
from services.resume_parser import ParsedResume

# Skills whose names collide with ordinary English. These need case-sensitive,
# tightly-bounded matching: a hyphen on either side rules the match out, so
# "C-level summary", "R-squared" and "go-to-market" are not programming
# languages, while "Languages: C, R, Go" still is.
_EDGE = r"[A-Za-z0-9+#\-]"
AMBIGUOUS: dict[str, str] = {
    "c": rf"(?<!{_EDGE})C(?!{_EDGE})",
    "r": rf"(?<!{_EDGE})R(?![A-Za-z0-9&\-])",
    "go": rf"(?<!{_EDGE})Go(?!{_EDGE})",
    "c++": r"C\s?\+\+",
    "c#": r"C\s?#",
    ".net": r"(?<![A-Za-z])\.NET(?:\s+Core)?|ASP\.NET",
}

SECTION_WEIGHTS: dict[str, float] = {
    "experience": 1.0,
    "projects": 0.92,
    "summary": 0.75,
    "skills": 0.7,
    "certifications": 0.7,
    "achievements": 0.65,
    "publications": 0.6,
    "leadership": 0.55,
    "education": 0.5,
    "header": 0.4,
    "other": 0.5,
}


@dataclass
class SkillEvidence:
    section: str
    snippet: str
    surface_form: str


@dataclass
class ExtractedSkill:
    name: str
    category: str
    category_label: str
    confidence: float
    mentions: int
    sections: list[str]
    evidence: list[SkillEvidence] = field(default_factory=list)
    applied: bool = False
    declared_only: bool = False
    quantified: bool = False
    emerging: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "category_label": self.category_label,
            "confidence": round(self.confidence, 3),
            "mentions": self.mentions,
            "sections": self.sections,
            "applied": self.applied,
            "declared_only": self.declared_only,
            "quantified": self.quantified,
            "emerging": self.emerging,
            "evidence": [
                {"section": e.section, "snippet": e.snippet, "matched": e.surface_form}
                for e in self.evidence[:3]
            ],
        }


class SkillExtractor:
    """Ontology-driven skill detection with evidence tracking."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or get_knowledge_base()
        self.nlp = get_pipeline()
        self._patterns: dict[str, re.Pattern] = {}
        self._build_patterns()

    def _build_patterns(self) -> None:
        for key, skill in self.kb.skills.items():
            if key in AMBIGUOUS:
                # The name itself is matched case-sensitively and tightly; the
                # aliases ("golang", "csharp") are unambiguous, so they keep
                # normal case-insensitive word-boundary matching.
                pattern = AMBIGUOUS[key]
                aliases = self._alternatives(skill.aliases)
                if aliases:
                    pattern = (
                        f"{pattern}|(?i:(?<![A-Za-z0-9])(?:{aliases})(?![A-Za-z0-9]))"
                    )
                self._patterns[key] = re.compile(pattern)
                continue

            alternatives = self._alternatives(skill.surface_forms())
            pattern = rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])"
            try:
                self._patterns[key] = re.compile(pattern, re.IGNORECASE)
            except re.error:  # pragma: no cover - defensive
                self._patterns[key] = re.compile(re.escape(skill.name), re.IGNORECASE)

    @staticmethod
    def _alternatives(forms: list[str]) -> str:
        """Regex alternation for a set of surface forms, longest first."""
        alternatives = []
        for form in forms:
            escaped = re.escape(form.strip())
            # Tolerate spacing/hyphenation differences: "scikit learn",
            # "scikit-learn" and "scikitlearn" all count.
            escaped = escaped.replace(r"\ ", r"[\s\-]?").replace(r"\-", r"[\s\-]?")
            if escaped:
                alternatives.append(escaped)
        alternatives.sort(key=len, reverse=True)
        return "|".join(alternatives)

    # -- extraction --------------------------------------------------------

    def extract(self, resume: ParsedResume) -> list[ExtractedSkill]:
        """Find every ontology skill evidenced anywhere in the resume."""
        searchable = self._searchable_blocks(resume)
        found: dict[str, ExtractedSkill] = {}

        for key, pattern in self._patterns.items():
            skill_def = self.kb.skills[key]
            hits: list[tuple[str, str, str]] = []  # section, snippet, surface
            for section, text in searchable:
                if not text:
                    continue
                for match in pattern.finditer(text):
                    snippet = _snippet(text, match.start(), match.end())
                    hits.append((section, snippet, match.group(0)))
                    if len(hits) >= 12:
                        break
            if not hits:
                continue

            sections = sorted({h[0] for h in hits})
            applied = any(s in {"experience", "projects"} for s in sections)
            declared_only = sections == ["skills"]
            base = max(SECTION_WEIGHTS.get(s, 0.5) for s in sections)
            # Repetition adds a little confidence, with diminishing returns.
            repetition_bonus = min(0.15, 0.04 * (len(hits) - 1))
            multi_section_bonus = 0.08 if len(sections) > 1 else 0.0
            confidence = min(1.0, base + repetition_bonus + multi_section_bonus)

            found[skill_def.name] = ExtractedSkill(
                name=skill_def.name,
                category=skill_def.category,
                category_label=self.kb.category_label(skill_def.category),
                confidence=confidence,
                mentions=len(hits),
                sections=sections,
                evidence=[SkillEvidence(s, snip, surface) for s, snip, surface in hits[:3]],
                applied=applied,
                declared_only=declared_only,
                quantified=any(find_metrics(h[1]) for h in hits),
                emerging=skill_def.emerging,
            )

        return sorted(found.values(), key=lambda s: (-s.confidence, -s.mentions, s.name))

    def extract_from_text(self, text: str, section: str = "other") -> list[str]:
        """Canonical skill names present in an arbitrary block of text."""
        names: list[str] = []
        for key, pattern in self._patterns.items():
            if pattern.search(text or ""):
                names.append(self.kb.skills[key].name)
        return names

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _searchable_blocks(resume: ParsedResume) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = [
            (name, body) for name, body in resume.sections.items() if body
        ]
        known = {name for name, _ in blocks}
        # Projects and experience text is also searched via the structured
        # entries so tech-stack lines that fell outside a heading still count.
        if "projects" not in known and resume.projects:
            blocks.append(("projects", "\n".join(p.raw for p in resume.projects)))
        if "experience" not in known and resume.experience:
            blocks.append(("experience", "\n".join(e.raw for e in resume.experience)))
        if not blocks:
            blocks.append(("other", resume.raw_text))
        return blocks

    # -- aggregation -------------------------------------------------------

    def group_by_category(self, skills: Iterable[ExtractedSkill]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for skill in skills:
            grouped[skill.category].append(skill.to_dict())
        return dict(grouped)

    def profile_summary(self, skills: list[ExtractedSkill]) -> dict[str, Any]:
        """High-level counts used by the dashboard's overview cards."""
        by_category: dict[str, int] = defaultdict(int)
        for skill in skills:
            by_category[skill.category] += 1
        applied = [s for s in skills if s.applied]
        return {
            "total": len(skills),
            "applied": len(applied),
            "declared_only": len([s for s in skills if s.declared_only]),
            "quantified": len([s for s in skills if s.quantified]),
            "emerging": [s.name for s in skills if s.emerging],
            "by_category": {
                self.kb.category_label(cat): count for cat, count in sorted(by_category.items())
            },
            "strongest": [s.name for s in skills[:8]],
        }

    def expand_related(self, skills: Iterable[ExtractedSkill]) -> list[str]:
        """Skill-graph expansion, used to give adjacent experience partial credit."""
        expanded: set[str] = set()
        for skill in skills:
            for related in self.kb.related_skills(skill.name):
                expanded.add(related)
        return sorted(expanded)


def _snippet(text: str, start: int, end: int, window: int = 90) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    fragment = text[left:right].replace("\n", " ").strip()
    return ("… " if left > 0 else "") + fragment + (" …" if right < len(text) else "")


_EXTRACTOR: SkillExtractor | None = None


def get_skill_extractor() -> SkillExtractor:
    global _EXTRACTOR
    if _EXTRACTOR is None:
        _EXTRACTOR = SkillExtractor()
    return _EXTRACTOR
