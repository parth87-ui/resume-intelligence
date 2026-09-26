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


# ---------------------------------------------------------------------------
# Tech-domain gate
# ---------------------------------------------------------------------------
#
# Everything this platform knows about is technical: the skill ontology, the
# company profiles, the project library and the scoring weights. Run a sales or
# nursing posting through it and the pipeline still produces a confident-looking
# number - one that means nothing, because it measured the resume against an
# ontology that does not describe the job. Refusing is more honest than scoring
# it badly, so a non-technical posting is blocked rather than warned about.

MIN_TECH_SKILLS = 3
"""Distinct non-soft ontology skills that clear the gate on their own."""

SIGNAL_OCCURRENCE_CAP = 3
"""Cap per term, so one word repeated 40 times cannot dominate the count."""

TECH_ROLE_TERMS: tuple[str, ...] = (
    "engineer", "engineering", "developer", "development", "sde", "software",
    "programmer", "data scientist", "machine learning", "deep learning", "ml",
    "ai", "artificial intelligence", "devops", "sre", "site reliability",
    "cloud", "backend", "back end", "frontend", "front end", "full stack",
    "qa", "quality assurance", "test engineer", "data engineer",
    "platform engineer", "architect", "technical", "codebase", "api",
)

NON_TECH_ROLE_TERMS: tuple[str, ...] = (
    "sales", "salesperson", "marketing", "human resources", "hr", "recruiter",
    "recruitment", "accountant", "accounting", "bookkeeping", "nurse",
    "nursing", "patient care", "teacher", "teaching", "tutor", "driver",
    "driving", "chef", "cook", "culinary", "customer support",
    "customer service", "receptionist", "cashier", "retail", "hospitality",
    "waiter", "housekeeping",
)

AMBIGUOUS_ROLE_TERMS: tuple[str, ...] = ("analyst", "analytics")
"""Counts as technical only alongside a technical tool - see assess_domain."""

AMBIGUOUS_TECH_PARTNERS: tuple[str, ...] = (
    "sql", "python", "tableau", "power bi", "pandas", "numpy", "spark", "etl",
)


class NonTechJobDescriptionError(ValueError):
    """Raised when a pasted posting is not a technical role.

    Subclasses ``ValueError`` so existing ``except ValueError`` handling still
    catches it; routes that want the specific 422 code catch it first.
    """

    def __init__(self, message: str, domain: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.domain = domain or {}


# ---------------------------------------------------------------------------
# Degree requirements
# ---------------------------------------------------------------------------

DEGREE_RANK = {"none": 0, "bachelor": 1, "master": 2, "phd": 3}

DEGREE_LABELS = {
    "none": "No degree stated",
    "bachelor": "Bachelor's degree",
    "master": "Master's degree",
    "phd": "PhD",
}

# Bare "MS"/"BS" is deliberately only matched when followed by "in" or a slash
# pair, so "MS Office" and "BS EN 1993" do not read as degree requirements.
_DEGREE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("phd", r"\b(?:ph\.?\s?d\.?|doctorate|doctoral\s+degree)\b"),
    (
        "master",
        r"\b(?:master'?s?(?:\s+degree)?|m\.?sc\.?|m\.?tech\.?|mba)\b"
        r"|\b(?:m\.?s\.?|m\.?a\.?)(?:\s*/\s*(?:b\.?s\.?|ph\.?d\.?))?\s*(?:degree\s*)?in\b",
    ),
    (
        "bachelor",
        r"\b(?:bachelor'?s?(?:\s+degree)?|b\.?sc\.?|b\.?tech\.?|undergraduate\s+degree)\b"
        r"|\b(?:b\.?s\.?|b\.?a\.?|b\.?e\.?)(?:\s*/\s*(?:m\.?s\.?|m\.?a\.?))?\s*(?:degree\s*)?in\b",
    ),
)

_DEGREE_FIELDS: tuple[tuple[str, str], ...] = (
    ("Computer Science", r"computer\s+science|\bcs\b|computer\s+engineering"),
    ("Data Science", r"data\s+science"),
    ("Mathematics or Statistics", r"mathematic|\bmaths?\b|statistic"),
    ("Engineering", r"engineering"),
    ("Information Technology", r"information\s+technology"),
)

_EQUIVALENT_RE = re.compile(
    r"or\s+equivalent|equivalent\s+(?:practical\s+)?experience|"
    r"or\s+relevant\s+(?:work\s+)?experience|in\s+lieu\s+of\s+a\s+degree",
    re.IGNORECASE,
)


class JobDescriptionParser:
    """Extracts structured requirements from free-text job descriptions."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or get_knowledge_base()
        self.extractor = get_skill_extractor()
        self.nlp = get_pipeline()

    # -- public ------------------------------------------------------------

    def assess_domain(self, text: str) -> dict[str, Any]:
        """Decide whether a posting is a technical role this platform can score.

        Three independent signals, so no single word decides it:

        * how many distinct non-soft ontology skills the posting names
        * technical role vocabulary (engineer, developer, ML, cloud, …)
        * non-technical role vocabulary (sales, nursing, hospitality, …)

        A posting is rejected only when it is weak on *both* counts: fewer than
        ``MIN_TECH_SKILLS`` technical skills **and** more non-technical wording
        than technical. A genuine ML posting that happens to mention "customer
        service" therefore still passes, and so does a sparse-but-technical one
        that names four tools without much prose.
        """
        raw = normalise_whitespace(text)
        skills = {
            name
            for name in self.extractor.extract_from_text(raw)
            if self.kb.category_of(name) != "soft"
        }
        tech_skill_count = len(skills)

        tech_score, tech_hits = _count_signals(raw, TECH_ROLE_TERMS)
        non_tech_score, non_tech_hits = _count_signals(raw, NON_TECH_ROLE_TERMS)

        # "Analyst" is the genuinely ambiguous one: a data analyst is in scope,
        # a financial analyst is not. It only counts as technical when the
        # posting also names a technical tool.
        ambiguous_score, ambiguous_hits = _count_signals(raw, AMBIGUOUS_ROLE_TERMS)
        partner_score, partner_hits = _count_signals(raw, AMBIGUOUS_TECH_PARTNERS)
        if ambiguous_score and partner_score:
            tech_score += ambiguous_score
            tech_hits.extend(ambiguous_hits)

        is_tech = not (tech_skill_count < MIN_TECH_SKILLS and non_tech_score > tech_score)

        # Confidence is distance from the decision boundary, not a probability.
        skill_evidence = min(1.0, tech_skill_count / (MIN_TECH_SKILLS * 2))
        if is_tech:
            margin = tech_score - non_tech_score
            confidence = 50 + 35 * skill_evidence + 15 * min(1.0, max(0, margin) / 4)
        else:
            confidence = 50 + 35 * min(1.0, (non_tech_score - tech_score) / 4) + 15 * (
                1 - skill_evidence
            )

        return {
            "is_tech": is_tech,
            "confidence": round(max(0.0, min(100.0, confidence)), 1),
            "tech_skill_count": tech_skill_count,
            "tech_signals": sorted(set(tech_hits)),
            "non_tech_signals": sorted(set(non_tech_hits)),
            "tech_signal_score": tech_score,
            "non_tech_signal_score": non_tech_score,
            "skills_found": sorted(skills)[:20],
            "tool_signals_for_analyst": sorted(set(partner_hits)) if ambiguous_hits else [],
        }

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

        # The domain gate runs before any parsing work: there is no point
        # extracting requirements from a posting we are going to refuse.
        domain = self.assess_domain(raw)
        if not domain["is_tech"]:
            raise NonTechJobDescriptionError(
                "This doesn't look like a tech job description. Resume Intelligence "
                "scores resumes against software, data, ML, cloud and other technical "
                "roles. Please paste a tech job posting.",
                domain=domain,
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
            "domain": domain,
            "degree_required": self._degree_requirement(required_text, raw),
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

    def _degree_requirement(self, required_text: str, full_text: str) -> dict[str, Any]:
        """Highest degree level the posting asks for, and in what field.

        The required block wins when it mentions a degree at all; otherwise the
        whole posting is searched, because plenty of postings state the degree
        in an intro paragraph rather than under a heading.
        """
        haystack = required_text if _mentions_degree(required_text) else full_text

        level = "none"
        evidence = ""
        for name, pattern in _DEGREE_PATTERNS:
            match = re.search(pattern, haystack, flags=re.IGNORECASE)
            if match and DEGREE_RANK[name] > DEGREE_RANK[level]:
                level = name
                evidence = _sentence_around(haystack, match.start())

        field = ""
        if level != "none":
            window = evidence or haystack
            for label, pattern in _DEGREE_FIELDS:
                if re.search(pattern, window, flags=re.IGNORECASE):
                    field = label
                    break
            if not field and re.search(r"related\s+(?:technical\s+)?field", window, re.IGNORECASE):
                field = "Related technical field"

        return {
            "level": level,
            "level_label": DEGREE_LABELS[level],
            "field": field,
            "stated": level != "none",
            # Recorded for transparency: many postings accept experience instead
            # of the stated degree, which is worth showing the candidate.
            "equivalent_allowed": bool(_EQUIVALENT_RE.search(evidence or haystack)),
            "evidence": evidence,
        }

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


def _count_signals(text: str, terms: tuple[str, ...]) -> tuple[int, list[str]]:
    """Total signal weight and which terms fired.

    Each term contributes its occurrence count capped at
    ``SIGNAL_OCCURRENCE_CAP``, so a posting that says "sales" thirty times
    counts as three - enough to beat a passing technical mention, not enough to
    swamp a genuinely technical posting.
    """
    total = 0
    hits: list[str] = []
    for term in terms:
        pattern = r"\b" + r"\s+".join(re.escape(word) for word in term.split()) + r"\b"
        found = len(re.findall(pattern, text, flags=re.IGNORECASE))
        if found:
            total += min(found, SIGNAL_OCCURRENCE_CAP)
            hits.append(term)
    return total, hits


def _mentions_degree(text: str) -> bool:
    return any(
        re.search(pattern, text, flags=re.IGNORECASE) for _, pattern in _DEGREE_PATTERNS
    )


def _sentence_around(text: str, index: int, window: int = 200) -> str:
    """The sentence containing ``index``, for showing why a rule fired."""
    enders = ".!?" + chr(10)
    start = index
    while start > 0 and text[start - 1] not in enders:
        start -= 1
    end = index
    while end < len(text) and text[end] not in enders:
        end += 1
    return text[start : end + 1].strip()[:window]


def _boilerplate(phrase: str) -> bool:
    return any(term in phrase for term in _BOILERPLATE_TERMS)


_JD_PARSER: JobDescriptionParser | None = None


def get_jd_parser() -> JobDescriptionParser:
    global _JD_PARSER
    if _JD_PARSER is None:
        _JD_PARSER = JobDescriptionParser()
    return _JD_PARSER
