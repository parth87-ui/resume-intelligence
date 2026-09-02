"""Company / role / skill knowledge base.

Loads the JSON datasets once, indexes them, and composes *effective* job
requirements for any (company, role, experience level) triple.

Composition order - each layer only refines the previous one:

    role baseline  ->  company profile  ->  experience level  ->  curated override

That is what makes the platform extensible: adding a company or role means
adding a JSON object, never touching analysis code.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from config import DATASETS_DIR


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class SkillDef:
    """One canonical skill from the ontology."""

    name: str
    category: str
    aliases: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    learn_weeks: int = 4
    emerging: bool = False

    @property
    def key(self) -> str:
        return self.name.lower()

    def surface_forms(self) -> list[str]:
        """All strings that should be treated as evidence of this skill."""
        return [self.name] + list(self.aliases)


@dataclass
class RequiredSkill:
    """A skill requirement with its importance and tier for a specific target."""

    skill: str
    importance: float
    tier: str  # required | preferred | optional
    category: str = ""
    source: str = "role"  # role | company | override | level

    @property
    def priority(self) -> str:
        if self.tier == "required" and self.importance >= 0.85:
            return "high"
        if self.importance >= 0.85:
            return "high"
        if self.importance >= 0.65:
            return "medium"
        return "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "importance": round(self.importance, 3),
            "tier": self.tier,
            "priority": self.priority,
            "category": self.category,
            "source": self.source,
        }


@dataclass
class JobRequirement:
    """The fully composed requirement profile the resume is scored against."""

    company_id: str
    company_name: str
    role_id: str
    role_title: str
    level_id: str
    level_title: str
    summary: str
    skills: list[RequiredSkill]
    keywords: list[str]
    responsibilities: list[str]
    soft_skills: list[str]
    values: list[str]
    hiring_signals: list[str]
    screen_notes: str
    interview_focus: list[str]
    expectations: list[str]
    expected_years: float
    weights: dict[str, float]
    radar_axes: list[str]
    curated: bool = False

    def by_tier(self, tier: str) -> list[RequiredSkill]:
        return [s for s in self.skills if s.tier == tier]

    def skill_names(self) -> list[str]:
        return [s.skill for s in self.skills]

    def requirement_text(self) -> str:
        """Flat text used by the TF-IDF / semantic similarity stage."""
        parts: list[str] = [self.role_title, self.company_name, self.summary]
        parts.extend(s.skill for s in self.skills)
        parts.extend(self.keywords)
        parts.extend(self.responsibilities)
        parts.extend(self.soft_skills)
        parts.extend(self.values)
        return " . ".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": {"id": self.company_id, "name": self.company_name},
            "role": {"id": self.role_id, "title": self.role_title},
            "level": {"id": self.level_id, "title": self.level_title},
            "summary": self.summary,
            "curated": self.curated,
            "expected_years": self.expected_years,
            "weights": self.weights,
            "radar_axes": self.radar_axes,
            "required_skills": [s.to_dict() for s in self.by_tier("required")],
            "preferred_skills": [s.to_dict() for s in self.by_tier("preferred")],
            "optional_skills": [s.to_dict() for s in self.by_tier("optional")],
            "keywords": self.keywords,
            "responsibilities": self.responsibilities,
            "soft_skills": self.soft_skills,
            "values": self.values,
            "hiring_signals": self.hiring_signals,
            "screen_notes": self.screen_notes,
            "interview_focus": self.interview_focus,
            "expectations": self.expectations,
        }


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


class KnowledgeBase:
    """Indexed access to the JSON datasets."""

    def __init__(self, datasets_dir=DATASETS_DIR) -> None:
        self.dir = datasets_dir
        self._lock = threading.Lock()
        self.reload()

    # -- loading -----------------------------------------------------------

    def _read(self, name: str) -> dict[str, Any]:
        path = self.dir / name
        if not path.exists():
            raise FileNotFoundError(f"Missing dataset file: {path}")
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def reload(self) -> None:
        """(Re)load every dataset and rebuild the indexes."""
        with self._lock:
            skills_doc = self._read("skills.json")
            self.skill_categories: dict[str, str] = skills_doc["categories"]
            self.skills: dict[str, SkillDef] = {}
            self._alias_index: dict[str, str] = {}

            for raw in skills_doc["skills"]:
                sd = SkillDef(
                    name=raw["name"],
                    category=raw.get("category", "tool"),
                    aliases=[a.lower() for a in raw.get("aliases", [])],
                    related=raw.get("related", []),
                    learn_weeks=int(raw.get("learn_weeks", 4)),
                    emerging=bool(raw.get("emerging", False)),
                )
                self.skills[sd.key] = sd
                self._alias_index[sd.key] = sd.name
                for alias in sd.aliases:
                    self._alias_index.setdefault(alias, sd.name)

            self.companies = {c["id"]: c for c in self._read("companies.json")["companies"]}
            self.roles = {r["id"]: r for r in self._read("roles.json")["roles"]}
            self.levels = {l["id"]: l for l in self._read("experience_levels.json")["levels"]}
            self.projects = self._read("projects.json")["projects"]

            overrides_doc = self._read("company_role_overrides.json")
            self.overrides: dict[tuple[str, str], dict[str, Any]] = {
                (o["company"], o["role"]): o for o in overrides_doc["overrides"]
            }

    # -- lookups -----------------------------------------------------------

    def canonical_skill(self, term: str) -> str | None:
        """Map any surface form to its canonical skill name."""
        return self._alias_index.get(term.strip().lower())

    def skill(self, name: str) -> SkillDef | None:
        canonical = self.canonical_skill(name)
        return self.skills.get(canonical.lower()) if canonical else None

    def category_of(self, skill_name: str) -> str:
        sd = self.skill(skill_name)
        return sd.category if sd else "tool"

    def category_label(self, category: str) -> str:
        return self.skill_categories.get(category, category.title())

    def learn_weeks(self, skill_name: str) -> int:
        sd = self.skill(skill_name)
        return sd.learn_weeks if sd else 4

    def is_emerging(self, skill_name: str) -> bool:
        sd = self.skill(skill_name)
        return bool(sd and sd.emerging)

    def related_skills(self, skill_name: str) -> list[str]:
        sd = self.skill(skill_name)
        return list(sd.related) if sd else []

    def list_companies(self) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "name": c["name"],
                "tagline": c["tagline"],
                "values": c["values"],
                "keywords": c["keywords"],
                "interview_focus": c.get("interview_focus", []),
                "curated_roles": sorted(
                    r for (comp, r) in self.overrides.keys() if comp == c["id"]
                ),
            }
            for c in self.companies.values()
        ]

    def list_roles(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "family": r["family"],
                "summary": r["summary"],
                "core_skills": [s["skill"] for s in r["required_skills"][:6]],
            }
            for r in self.roles.values()
        ]

    def list_levels(self) -> list[dict[str, Any]]:
        return [
            {
                "id": l["id"],
                "title": l["title"],
                "expected_years": l["expected_years"],
                "expectations": l["expectations"],
                "weights": l["weights"],
            }
            for l in self.levels.values()
        ]

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "category": s.category,
                "category_label": self.category_label(s.category),
                "aliases": s.aliases,
                "learn_weeks": s.learn_weeks,
                "emerging": s.emerging,
            }
            for s in self.skills.values()
        ]

    # -- requirement composition ------------------------------------------

    def build_requirement(
        self, company_id: str, role_id: str, level_id: str = "entry"
    ) -> JobRequirement:
        """Compose the effective requirement profile for a target."""
        role = self.roles.get(role_id)
        if role is None:
            raise KeyError(f"Unknown role '{role_id}'")
        company = self.companies.get(company_id)
        if company is None:
            raise KeyError(f"Unknown company '{company_id}'")
        level = self.levels.get(level_id) or self.levels["entry"]

        # Layer 1 - role baseline -----------------------------------------
        acc: dict[str, RequiredSkill] = {}

        def put(skill_name: str, importance: float, tier: str, source: str) -> None:
            canonical = self.canonical_skill(skill_name) or skill_name
            key = canonical.lower()
            existing = acc.get(key)
            if existing is None:
                acc[key] = RequiredSkill(
                    skill=canonical,
                    importance=min(1.0, importance),
                    tier=tier,
                    category=self.category_of(canonical),
                    source=source,
                )
                return
            # Keep the strongest signal seen for the skill.
            if _tier_rank(tier) > _tier_rank(existing.tier):
                existing.tier = tier
                existing.source = source
            if importance > existing.importance:
                existing.importance = min(1.0, importance)
                existing.source = source

        for tier in ("required", "preferred", "optional"):
            for entry in role.get(f"{tier}_skills", []):
                put(entry["skill"], float(entry["importance"]), tier, "role")

        for soft in role.get("soft_skills", []):
            put(soft, 0.55, "preferred", "role")

        keywords = list(role.get("keywords", []))
        responsibilities = list(role.get("responsibilities", []))

        # Layer 2 - company profile ---------------------------------------
        for focus in company.get("focus_skills", []):
            name = focus["skill"]
            canonical = self.canonical_skill(name) or name
            key = canonical.lower()
            boost = float(focus.get("boost", 0.1))
            promote = focus.get("promote_to")
            if key in acc:
                acc[key].importance = min(1.0, acc[key].importance + boost)
                if promote and _tier_rank(promote) > _tier_rank(acc[key].tier):
                    acc[key].tier = promote
                acc[key].source = "company"
            else:
                # A skill the company screens for that the generic role does
                # not list is still relevant - it enters as preferred (or the
                # promoted tier) with the boost as its base importance.
                put(canonical, 0.5 + boost, promote or "preferred", "company")

        keywords = _merge_unique(keywords, company.get("keywords", []))

        # Layer 3 - curated override --------------------------------------
        override = self.overrides.get((company_id, role_id))
        if override:
            for entry in override.get("extra_required", []):
                put(entry["skill"], float(entry["importance"]), "required", "override")
            for entry in override.get("extra_preferred", []):
                put(entry["skill"], float(entry["importance"]), "preferred", "override")
            keywords = _merge_unique(keywords, override.get("keywords", []))
            responsibilities = _merge_unique(
                responsibilities, override.get("responsibilities", [])
            )

        # Layer 4 - experience level --------------------------------------
        scale = float(level.get("importance_scale", 1.0))
        for req in acc.values():
            req.importance = round(min(1.0, req.importance * scale), 3)

        skills = sorted(
            acc.values(),
            key=lambda s: (-_tier_rank(s.tier), -s.importance, s.skill.lower()),
        )

        summary_bits = [role["summary"], company["tagline"]]
        if override and override.get("notes"):
            summary_bits.append(override["notes"])

        return JobRequirement(
            company_id=company_id,
            company_name=company["name"],
            role_id=role_id,
            role_title=role["title"],
            level_id=level["id"],
            level_title=level["title"],
            summary=" ".join(summary_bits),
            skills=skills,
            keywords=keywords,
            responsibilities=responsibilities,
            soft_skills=role.get("soft_skills", []),
            values=company.get("values", []),
            hiring_signals=company.get("hiring_signals", []),
            screen_notes=(override or {}).get("notes") or company.get("screen_notes", ""),
            interview_focus=company.get("interview_focus", []),
            expectations=level.get("expectations", []),
            expected_years=float(level.get("expected_years", 0)),
            weights=dict(level.get("weights", {})),
            radar_axes=role.get("radar_axes", ["ml", "cloud", "cs", "data", "devops"]),
            curated=override is not None,
        )


def _tier_rank(tier: str) -> int:
    return {"optional": 1, "preferred": 2, "required": 3}.get(tier, 0)


def _merge_unique(base: Iterable[str], extra: Iterable[str]) -> list[str]:
    seen: dict[str, str] = {}
    for item in list(base) + list(extra):
        key = item.strip().lower()
        if key and key not in seen:
            seen[key] = item.strip()
    return list(seen.values())


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    """Process-wide singleton (datasets are read-only at runtime)."""
    return KnowledgeBase()
