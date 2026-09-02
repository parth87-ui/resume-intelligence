"""Job description analysis.

Turns a pasted job description into the same :class:`JobRequirement` structure
the curated datasets produce, so a real posting flows through the identical
matching, scoring, ATS and recommendation pipeline.

It can also be *fused* with a curated company/role target: the JD supplies the
hard requirements, the company profile supplies the cultural and keyword layer.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ml.nlp_pipeline import STOPWORDS, find_years_of_experience, get_pipeline, normalise_whitespace
from services.knowledge_base import (
    JobRequirement,
    KnowledgeBase,
    RequiredSkill,
    get_knowledge_base,
)
from services.skill_extractor import get_skill_extractor

REQUIRED_HEADINGS = [
    "basic qualifications", "minimum qualifications", "required qualifications",
    "requirements", "qualifications", "what you need", "must have", "who you are",
    "required skills", "essential skills", "we are looking for",
]
PREFERRED_HEADINGS = [
    "preferred qualifications", "preferred skills", "nice to have", "bonus points",
    "bonus", "desired skills", "good to have", "preferred experience", "pluses",
]
RESPONSIBILITY_HEADINGS = [
    "responsibilities", "what you'll do", "what you will do", "the role",
    "your impact", "duties", "job description", "about the role", "day to day",
]

_HEADING_RE = re.compile(r"^[\s#*>-]*([A-Za-z][A-Za-z'’\s/&]{3,45})\s*:?\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•‣●▪·]|\d+[.)])\s+")


class JobDescriptionParser:
    """Extracts structured requirements from free-text job descriptions."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or get_knowledge_base()
        self.extractor = get_skill_extractor()
        self.nlp = get_pipeline()

    # -- public ------------------------------------------------------------

    def parse(
        self,
        text: str,
        company_name: str = "",
        role_title: str = "",
        level_id: str = "mid",
    ) -> tuple[JobRequirement, dict[str, Any]]:
        raw = normalise_whitespace(text)
        if len(raw.split()) < 30:
            raise ValueError(
                "This job description is too short to analyse. Paste the full posting "
                "including the requirements and responsibilities sections."
            )

        blocks = self._split_blocks(raw)
        required_text = blocks.get("required", "")
        preferred_text = blocks.get("preferred", "")
        responsibilities_text = blocks.get("responsibilities", "")
        other_text = blocks.get("other", "")

        required = self._skills_in(required_text, base=0.9)
        preferred = self._skills_in(preferred_text, base=0.7)
        fallback = self._skills_in(other_text + "\n" + responsibilities_text, base=0.6)

        # A skill named in the required block wins over any softer mention.
        skills: dict[str, RequiredSkill] = {}
        for name, importance in fallback.items():
            skills[name.lower()] = RequiredSkill(name, importance, "preferred", self.kb.category_of(name), "jd")
        for name, importance in preferred.items():
            skills[name.lower()] = RequiredSkill(name, importance, "preferred", self.kb.category_of(name), "jd")
        for name, importance in required.items():
            skills[name.lower()] = RequiredSkill(name, importance, "required", self.kb.category_of(name), "jd")

        if not skills:
            raise ValueError(
                "No recognisable technical skills were found in this job description. "
                "Check that you pasted the requirements section."
            )

        keywords = self._keywords(raw)
        responsibilities = self._bullets(responsibilities_text or other_text)
        years = find_years_of_experience(required_text or raw)
        level = self._infer_level(raw, years, level_id)

        detected_company = company_name.strip() or self._detect_company(raw)
        detected_role = role_title.strip() or self._detect_role(raw)

        requirement = JobRequirement(
            company_id="custom",
            company_name=detected_company or "Pasted job description",
            role_id="custom",
            role_title=detected_role or "Target role",
            level_id=level["id"],
            level_title=level["title"],
            summary=(raw[:400] + "…") if len(raw) > 400 else raw,
            skills=sorted(
                skills.values(),
                key=lambda s: (-(3 if s.tier == "required" else 2), -s.importance, s.skill),
            ),
            keywords=keywords,
            responsibilities=responsibilities,
            soft_skills=[s.skill for s in skills.values() if s.category == "soft"],
            values=[],
            hiring_signals=[],
            screen_notes="Requirements were extracted directly from the job description you pasted.",
            interview_focus=[],
            expectations=level.get("expectations", []),
            expected_years=years or float(level.get("expected_years", 2)),
            weights=dict(level.get("weights", {})),
            radar_axes=self._radar_axes(skills.values()),
            curated=False,
        )

        analysis = {
            "detected_company": detected_company,
            "detected_role": detected_role,
            "detected_level": level["title"],
            "years_required": years,
            "required_skills": [s.to_dict() for s in requirement.skills if s.tier == "required"],
            "preferred_skills": [s.to_dict() for s in requirement.skills if s.tier == "preferred"],
            "responsibilities": responsibilities,
            "keywords": keywords,
            "sections_found": sorted(k for k, v in blocks.items() if v.strip()),
            "word_count": len(raw.split()),
        }
        return requirement, analysis

    def fuse_with_target(
        self, jd_requirement: JobRequirement, company_id: str, role_id: str, level_id: str
    ) -> JobRequirement:
        """Combine a pasted JD with a curated company/role profile.

        The JD's explicit requirements take precedence; the curated profile adds
        the company's cultural signals, keywords and screening notes.
        """
        curated = self.kb.build_requirement(company_id, role_id, level_id)
        merged: dict[str, RequiredSkill] = {s.skill.lower(): s for s in curated.skills}
        for skill in jd_requirement.skills:
            key = skill.skill.lower()
            existing = merged.get(key)
            if existing is None or skill.importance > existing.importance:
                merged[key] = skill

        keywords = list(dict.fromkeys(jd_requirement.keywords + curated.keywords))
        return JobRequirement(
            company_id=curated.company_id,
            company_name=curated.company_name,
            role_id=curated.role_id,
            role_title=curated.role_title,
            level_id=curated.level_id,
            level_title=curated.level_title,
            summary=f"{curated.summary} Requirements fused with the job description you pasted.",
            skills=sorted(
                merged.values(),
                key=lambda s: (-(3 if s.tier == "required" else 2), -s.importance, s.skill),
            ),
            keywords=keywords,
            responsibilities=list(
                dict.fromkeys(jd_requirement.responsibilities + curated.responsibilities)
            ),
            soft_skills=curated.soft_skills,
            values=curated.values,
            hiring_signals=curated.hiring_signals,
            screen_notes=curated.screen_notes,
            interview_focus=curated.interview_focus,
            expectations=curated.expectations,
            expected_years=max(curated.expected_years, jd_requirement.expected_years),
            weights=curated.weights,
            radar_axes=curated.radar_axes,
            curated=True,
        )

    # -- internals ---------------------------------------------------------

    def _split_blocks(self, text: str) -> dict[str, str]:
        blocks: dict[str, list[str]] = {
            "required": [], "preferred": [], "responsibilities": [], "other": []
        }
        current = "other"
        for line in text.split("\n"):
            heading = self._classify_heading(line)
            if heading:
                current = heading
                continue
            blocks[current].append(line)
        return {k: "\n".join(v).strip() for k, v in blocks.items()}

    @staticmethod
    def _classify_heading(line: str) -> str | None:
        stripped = line.strip().rstrip(":").lower()
        if not stripped or len(stripped) > 60 or _BULLET_RE.match(line):
            return None
        if not _HEADING_RE.match(line.strip()):
            # Also allow "Preferred Qualifications:" style with punctuation
            if not line.strip().endswith(":"):
                return None
        for heading in PREFERRED_HEADINGS:
            if heading in stripped:
                return "preferred"
        for heading in REQUIRED_HEADINGS:
            if heading in stripped:
                return "required"
        for heading in RESPONSIBILITY_HEADINGS:
            if heading in stripped:
                return "responsibilities"
        return None

    def _skills_in(self, text: str, base: float) -> dict[str, float]:
        """Skills present in a block, with importance from mention frequency."""
        if not text.strip():
            return {}
        found: dict[str, float] = {}
        for name in self.extractor.extract_from_text(text):
            occurrences = len(
                re.findall(re.escape(name.split()[0]), text, flags=re.IGNORECASE)
            )
            bonus = min(0.09, 0.03 * (occurrences - 1))
            found[name] = round(min(1.0, base + bonus), 3)
        return found

    def _keywords(self, text: str, limit: int = 18) -> list[str]:
        ranked = self.nlp.keywords(text, top_n=90)
        skill_terms = {s.lower() for s in self.extractor.extract_from_text(text)}
        keywords: list[str] = []
        for phrase, count in ranked:
            if len(phrase.split()) < 2:
                continue
            if phrase in skill_terms or count < 2:
                continue
            if any(w in STOPWORDS for w in phrase.split()):
                continue
            if any(_boilerplate(phrase) for _ in [0]):
                continue
            keywords.append(phrase)
            if len(keywords) >= limit:
                break
        return keywords

    @staticmethod
    def _bullets(text: str) -> list[str]:
        items = []
        for line in text.split("\n"):
            if _BULLET_RE.match(line):
                cleaned = _BULLET_RE.sub("", line).strip()
                if len(cleaned.split()) >= 4:
                    items.append(cleaned)
        if not items:
            items = [
                s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 6
            ]
        return items[:12]

    def _infer_level(self, text: str, years: float, requested: str) -> dict[str, Any]:
        lowered = text.lower()
        if any(k in lowered for k in ("intern", "internship", "co-op")):
            return self.kb.levels["intern"]
        if any(k in lowered for k in ("senior", "staff", "principal", "lead engineer")) or years >= 5:
            return self.kb.levels["senior"]
        if any(k in lowered for k in ("entry level", "new grad", "graduate", "junior")) or years <= 1:
            return self.kb.levels["entry"]
        if 2 <= years < 5:
            return self.kb.levels["mid"]
        return self.kb.levels.get(requested, self.kb.levels["mid"])

    def _detect_company(self, text: str) -> str:
        for known in self.kb.companies.values():
            if re.search(rf"\b{re.escape(known['name'])}\b", text, re.I):
                return known["name"]
        match = re.search(r"\bat\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,2})", text)
        return match.group(1).strip() if match else ""

    def _detect_role(self, text: str) -> str:
        head = "\n".join(text.split("\n")[:6])
        for role in self.kb.roles.values():
            if re.search(rf"\b{re.escape(role['title'])}\b", text, re.I):
                return role["title"]
        match = re.search(
            r"\b((?:Senior|Staff|Lead|Junior)?\s*[A-Z][A-Za-z]+\s+(?:Engineer|Developer|Scientist|Analyst|Architect))\b",
            head,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _radar_axes(skills) -> list[str]:
        counts = Counter(s.category for s in skills)
        return [category for category, _ in counts.most_common(5)]


_BOILERPLATE_TERMS = {
    "equal opportunity", "reasonable accommodation", "background check", "cover letter",
    "compensation package", "benefit package", "click apply", "job type", "full time",
}


def _boilerplate(phrase: str) -> bool:
    return any(term in phrase for term in _BOILERPLATE_TERMS)


_JD_PARSER: JobDescriptionParser | None = None


def get_jd_parser() -> JobDescriptionParser:
    global _JD_PARSER
    if _JD_PARSER is None:
        _JD_PARSER = JobDescriptionParser()
    return _JD_PARSER
