"""AI resume improvement and career assistant.

Two execution paths, one contract:

* **Rule-based engine (always available).** Deterministic rewrites derived from
  the candidate's own words - stronger verbs, tighter structure, explicit
  technologies they actually used, and *placeholders* where a metric is
  missing. It never introduces a fact that is not already in the resume.

* **LLM engine (optional, enabled by ANTHROPIC_API_KEY).** The same job, with a
  system prompt that hard-codes the honesty rules below and a post-check that
  rejects any rewrite introducing an unsupported number.

THE HONESTY CONTRACT - enforced in both paths:
    1. Never invent skills, employers, projects, certifications or dates.
    2. Never introduce a metric the candidate did not provide. Where a metric
       would strengthen a bullet, emit a bracketed placeholder instead.
    3. Missing skills are framed as "build this, then claim it" - never as
       "add this to your resume".
    4. Every rewrite is labelled SUGGESTED REWRITE and must be verified.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from config import settings
from ml.nlp_pipeline import ACTION_VERBS, WEAK_OPENERS, find_metrics
from services.job_matcher import MatchResult
from services.resume_parser import ParsedResume

VERIFY_LABEL = "SUGGESTED REWRITE — verify every detail against what you actually did before using."

METRIC_PLACEHOLDER_HINTS: dict[str, str] = {
    "ml": "[add a measurable result — e.g. accuracy/F1 change, dataset size, inference latency]",
    "data": "[add a measurable result — e.g. rows processed, pipeline runtime, SLA met]",
    "cloud": "[add a measurable result — e.g. cost saved, uptime, requests served]",
    "devops": "[add a measurable result — e.g. deploy time, failure rate, MTTR]",
    "cs": "[add a measurable result — e.g. latency, throughput, complexity improvement]",
    "default": "[add a measurable result — e.g. %, time saved, users, scale]",
}

# Weak opener -> stronger alternatives, chosen by what the bullet is about.
VERB_UPGRADES: dict[str, list[str]] = {
    "worked": ["Built", "Developed", "Delivered"],
    "responsible": ["Owned", "Managed"],
    "handled": ["Managed", "Resolved"],
    "made": ["Built", "Created"],
    "did": ["Executed", "Delivered"],
    "used": ["Applied", "Leveraged"],
    "learned": ["Applied", "Adopted"],
    "created": ["Designed and built"],
    "wrote": ["Authored", "Implemented"],
}

# Weak verbs that describe a *support* role. These are never upgraded to
# ownership verbs - doing so would overstate the candidate's contribution,
# which is exactly what this tool refuses to do.
NON_INFLATING_OPENERS: set[str] = {
    "helped", "assisted", "participated", "involved", "contributed", "supported", "aided",
}

CONTEXT_VERBS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(model|train|classif|predict|neural|accuracy)\b", re.I), "Trained"),
    (re.compile(r"\b(deploy|production|endpoint|docker|kubernetes)\b", re.I), "Deployed"),
    (re.compile(r"\b(pipeline|etl|ingest|warehouse)\b", re.I), "Engineered"),
    (re.compile(r"\b(api|service|backend|endpoint)\b", re.I), "Built"),
    (re.compile(r"\b(dashboard|report|visuali|chart)\b", re.I), "Built"),
    (re.compile(r"\b(optimis|optimiz|improve|reduc|speed|faster|latency)\b", re.I), "Optimised"),
    # Deliberately no "team -> Led" rule: promoting collaboration into
    # leadership would overstate the candidate's actual role.
    (re.compile(r"\b(test|qa|coverage|bug)\b", re.I), "Tested"),
    (re.compile(r"\b(research|analys|analyz|stud)\b", re.I), "Analysed"),
]

FILLER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(?:i|we)\s+(?:was|were)\s+responsible for\s+", re.I), "Owned "),
    (re.compile(r"^\s*responsible for\s+", re.I), "Owned "),
    (re.compile(r"\bin order to\b", re.I), "to"),
    (re.compile(r"\bvarious\s+", re.I), ""),
    (re.compile(r"\bsuccessfully\s+", re.I), ""),
    (re.compile(r"\bvery\s+", re.I), ""),
    (re.compile(r"\ba lot of\b", re.I), ""),
    (re.compile(r"\betc\.?\b", re.I), ""),
    (re.compile(r"\bstuff\b", re.I), "components"),
    (re.compile(r"\bthings\b", re.I), "components"),
]


@dataclass
class Suggestion:
    section: str
    kind: str  # rewrite | add | restructure | caution
    original: str
    suggested: str
    rationale: str
    tags: list[str] = field(default_factory=list)
    requires_verification: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "kind": self.kind,
            "original": self.original,
            "suggested": self.suggested,
            "rationale": self.rationale,
            "tags": self.tags,
            "label": VERIFY_LABEL if self.requires_verification else "",
            "requires_verification": self.requires_verification,
        }


class AIService:
    """Section-by-section resume improvement with a strict honesty contract."""

    def __init__(self) -> None:
        self.llm_enabled = settings.llm_enabled

    def engine_info(self) -> dict[str, Any]:
        return {
            "mode": "llm" if self.llm_enabled else "rule-based",
            "model": settings.LLM_MODEL if self.llm_enabled else None,
            "note": (
                "Generative rewrites are produced by the configured LLM under the honesty "
                "contract, then screened for invented metrics."
                if self.llm_enabled
                else "No API key configured - using the deterministic rewrite engine. "
                "Set ANTHROPIC_API_KEY in .env to enable generative rewrites."
            ),
            "honesty_rules": [
                "Never invent skills, employers, projects, certifications or dates",
                "Never introduce a metric the candidate did not provide",
                "Frame missing skills as 'build it, then claim it'",
                "Label every rewrite for human verification",
            ],
        }

    # -- main entry point --------------------------------------------------

    def improve_resume(
        self, resume: ParsedResume, match: MatchResult, ats: dict[str, Any]
    ) -> dict[str, Any]:
        sections = {
            "summary": self._improve_summary(resume, match),
            "skills": self._improve_skills(resume, match),
            "experience": self._improve_experience(resume, match),
            "projects": self._improve_projects(resume, match),
            "education": self._improve_education(resume, match),
        }

        llm_note = None
        if self.llm_enabled:
            try:
                enriched = self._llm_rewrites(resume, match)
                for section, extra in enriched.items():
                    sections.setdefault(section, []).extend(extra)
                llm_note = "Generative rewrites merged from the configured LLM."
            except Exception as exc:  # never fail the analysis because of the LLM
                llm_note = f"LLM rewrites unavailable ({exc}); rule-based suggestions shown."

        return {
            "engine": self.engine_info(),
            "llm_note": llm_note,
            "sections": {
                name: [s.to_dict() for s in items] for name, items in sections.items()
            },
            "ethics": {
                "principle": "Optimise presentation of genuine experience, but never fabricate credentials or achievements.",
                "what_this_tool_will_not_do": [
                    "Write experience you have not had",
                    "Insert a company, degree or certification you do not hold",
                    "Fill in a metric you did not measure",
                ],
                "how_to_use_a_suggestion": [
                    "Read the rewrite next to your original",
                    "Replace every [bracketed placeholder] with a real number you can defend",
                    "Delete any clause that overstates what you did",
                ],
            },
            "priority_actions": self._priority_actions(resume, match, ats),
        }

    # -- section engines ---------------------------------------------------

    def _improve_summary(self, resume: ParsedResume, match: MatchResult) -> list[Suggestion]:
        req = match.requirement
        current = (resume.sections.get("summary") or "").strip()
        matched = [m.skill for m in match.matched()][:6]
        years = match.experience_analysis["detected_years"]

        skills_phrase = ", ".join(matched[:4]) if matched else "your strongest verified skills"
        experience_phrase = (
            f"{years:g} years of hands-on experience" if years >= 1 else "hands-on project experience"
        )
        scaffold = (
            f"{req.role_title} candidate with {experience_phrase} across {skills_phrase}. "
            f"[one line on your most relevant project or role — what you built and its measurable result]. "
            f"Targeting {req.role_title.lower()} work at {req.company_name}, with focus on "
            f"{', '.join(req.keywords[:2]) if req.keywords else 'production delivery'}."
        )

        if not current:
            return [
                Suggestion(
                    section="summary",
                    kind="add",
                    original="(no professional summary detected)",
                    suggested=scaffold,
                    rationale=(
                        f"A 2-3 line summary is the first thing a {req.company_name} recruiter reads "
                        "and the fastest place to align vocabulary with the role. The scaffold uses "
                        "only skills already detected in your resume - fill the bracketed line with "
                        "your own real achievement."
                    ),
                    tags=["missing-section", "keyword-alignment"],
                )
            ]

        suggestions: list[Suggestion] = []
        if len(current.split()) > 90:
            suggestions.append(
                Suggestion(
                    section="summary",
                    kind="restructure",
                    original=current[:400],
                    suggested=scaffold,
                    rationale=(
                        f"Your summary runs to {len(current.split())} words. Two or three lines "
                        "read better and survive a 6-second first scan."
                    ),
                    tags=["length"],
                )
            )
        generic = [p for p in ("hard working", "hardworking", "team player", "passionate",
                               "quick learner", "detail oriented", "highly motivated")
                   if p in current.lower()]
        if generic:
            suggestions.append(
                Suggestion(
                    section="summary",
                    kind="rewrite",
                    original=current[:400],
                    suggested=scaffold,
                    rationale=(
                        f"Phrases like '{generic[0]}' appear on most resumes and carry no signal. "
                        "Replace them with specific, verifiable capability."
                    ),
                    tags=["generic-language"],
                )
            )
        if not any(k.lower() in current.lower() for k in req.keywords[:6]) and req.keywords:
            suggestions.append(
                Suggestion(
                    section="summary",
                    kind="rewrite",
                    original=current[:400],
                    suggested=scaffold,
                    rationale=(
                        f"None of {req.company_name}'s recurring vocabulary appears in your summary "
                        f"(for example: {', '.join(req.keywords[:3])}). Use their words only where "
                        "they describe work you genuinely did."
                    ),
                    tags=["keyword-alignment"],
                )
            )
        return _dedupe(suggestions)[:3]

    def _improve_skills(self, resume: ParsedResume, match: MatchResult) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        req = match.requirement
        declared_only = [m for m in match.partial() if not m.via]
        adjacent = [m for m in match.partial() if m.via]

        if declared_only:
            names = ", ".join(m.skill for m in declared_only[:5])
            suggestions.append(
                Suggestion(
                    section="skills",
                    kind="restructure",
                    original=f"Listed but never demonstrated: {names}",
                    suggested=(
                        f"For each of {names}, add one bullet under the project or role where you "
                        "actually used it. Format: <strong verb> <what you built> using <skill> "
                        "<measurable outcome or placeholder>."
                    ),
                    rationale=(
                        "Reviewers discount a skills list that no bullet supports, and modern ATS "
                        "scoring weights context over keyword presence. This is a presentation fix, "
                        "not a new claim."
                    ),
                    tags=["skill-placement", "high-impact"],
                )
            )

        if adjacent:
            for m in adjacent[:3]:
                suggestions.append(
                    Suggestion(
                        section="skills",
                        kind="caution",
                        original=f"{m.skill} — not stated, adjacent to your {m.via} experience",
                        suggested=(
                            f"If you have genuinely used {m.skill} (even in coursework or a personal "
                            f"project), name it explicitly next to your {m.via} work. If you have not, "
                            f"leave it out — the roadmap shows the fastest honest way to acquire it."
                        ),
                        rationale=(
                            f"{req.company_name} screens for {m.skill} in this role. Adjacent "
                            f"experience earns partial credit but the explicit term is what the "
                            f"keyword filter looks for."
                        ),
                        tags=["honest-gap"],
                        requires_verification=False,
                    )
                )

        # Grouping check
        skills_block = resume.sections.get("skills", "")
        if skills_block and ":" not in skills_block and len(resume.skill_section_terms) > 12:
            suggestions.append(
                Suggestion(
                    section="skills",
                    kind="restructure",
                    original=skills_block[:300],
                    suggested=(
                        "Languages: …\nML & Data: …\nCloud & DevOps: …\nDatabases: …\nTools: …\n"
                        "(group your existing skills under these labels — do not add new ones)"
                    ),
                    rationale=(
                        f"{len(resume.skill_section_terms)} skills in an unlabelled block are hard "
                        "to scan. Grouped categories let a reviewer find the relevant stack in seconds."
                    ),
                    tags=["formatting"],
                )
            )
        return suggestions[:5]

    def _improve_experience(self, resume: ParsedResume, match: MatchResult) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        bullets: list[tuple[str, str]] = []
        for entry in resume.experience:
            for bullet in entry.bullets:
                bullets.append((entry.title or entry.organisation or "Experience", bullet))
        if not bullets:
            bullets = [("Experience", b) for b in resume.bullets[:8]]

        scored = sorted(bullets, key=lambda pair: -_weakness_score(pair[1]))
        for context, bullet in scored[:6]:
            rewrite, reasons, tags = self._rewrite_bullet(bullet, match)
            if not reasons:
                continue
            suggestions.append(
                Suggestion(
                    section="experience",
                    kind="rewrite",
                    original=bullet,
                    suggested=rewrite,
                    rationale=f"{context}: " + " ".join(reasons),
                    tags=tags,
                )
            )
        return suggestions

    def _improve_projects(self, resume: ParsedResume, match: MatchResult) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        req = match.requirement

        if not resume.projects:
            suggestions.append(
                Suggestion(
                    section="projects",
                    kind="add",
                    original="(no projects section detected)",
                    suggested=(
                        "Projects\n<Project name> — <one line on the problem>\n"
                        "- <verb> <what you built> using <technologies you actually used>\n"
                        "- <verb> <what you measured> [add the real number]\n"
                        "- Link: <repository or demo URL>"
                    ),
                    rationale=(
                        f"For a {req.level_title.lower()} {req.role_title} application, projects "
                        f"carry {req.weights.get('projects', 0.15) * 100:.0f}% of the match score and "
                        "are the only honest place to evidence newly-learned skills."
                    ),
                    tags=["missing-section", "high-impact"],
                )
            )
            return suggestions

        for project in resume.projects[:5]:
            issues: list[str] = []
            tags: list[str] = []
            if not find_metrics(project.raw):
                issues.append("no measurable outcome is stated")
                tags.append("quantify")
            if not re.search(r"https?://|github\.com|gitlab\.com|demo", project.raw, re.I):
                issues.append("no repository or demo link")
                tags.append("evidence")
            if len(project.bullets) < 2:
                issues.append("only one line of detail")
                tags.append("depth")
            if not project.tech_hint and not re.search(r"using|built with|stack", project.raw, re.I):
                issues.append("the technology stack is not stated explicitly")
                tags.append("keyword-alignment")
            if not issues:
                continue

            suggested = (
                f"{project.name}\n"
                f"- <strong verb> <what the system does> using <the technologies you actually used>\n"
                f"- <verb> <how you evaluated it> "
                f"{METRIC_PLACEHOLDER_HINTS.get(_dominant_category(match), METRIC_PLACEHOLDER_HINTS['default'])}\n"
                f"- Link: <repository or live demo>"
            )
            suggestions.append(
                Suggestion(
                    section="projects",
                    kind="rewrite",
                    original=project.raw[:400],
                    suggested=suggested,
                    rationale=(
                        f"'{project.name}' currently has {', '.join(issues)}. "
                        f"{req.company_name} reviewers look for what you built, what you used and "
                        "what it achieved - all three, in that order."
                    ),
                    tags=tags,
                )
            )
        return suggestions[:5]

    def _improve_education(self, resume: ParsedResume, match: MatchResult) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        req = match.requirement
        if not resume.education:
            suggestions.append(
                Suggestion(
                    section="education",
                    kind="add",
                    original="(no education section detected)",
                    suggested="Education\n<Degree>, <Field> — <Institution>, <Year>\n<GPA/percentage if strong>",
                    rationale="Most ATS pipelines expect a parseable education block with degree, institution and year.",
                    tags=["missing-section"],
                )
            )
            return suggestions

        for entry in resume.education:
            if not entry.year:
                suggestions.append(
                    Suggestion(
                        section="education",
                        kind="rewrite",
                        original=entry.raw[:200],
                        suggested=f"{entry.degree or '<Degree>'}, <Field> — {entry.institution or '<Institution>'}, <Graduation year>",
                        rationale="No graduation year was detected on this entry; recruiters use it to infer level.",
                        tags=["formatting"],
                    )
                )
                break

        if not resume.certifications and req.company_id in {"amazon", "microsoft", "ibm", "google"}:
            suggestions.append(
                Suggestion(
                    section="education",
                    kind="caution",
                    original="(no certifications listed)",
                    suggested=(
                        f"If you hold any cloud or ML certification, list it here with the issuer and "
                        f"date. If you do not, treat this as a roadmap item — a relevant "
                        f"{'AWS' if req.company_id == 'amazon' else 'cloud'} certification is one of the "
                        f"faster credible signals for {req.company_name}."
                    ),
                    rationale=f"{req.company_name} screens weight recognised certifications more than most.",
                    tags=["honest-gap"],
                    requires_verification=False,
                )
            )
        return suggestions[:4]

    # -- bullet rewriting --------------------------------------------------

    def _rewrite_bullet(self, bullet: str, match: MatchResult) -> tuple[str, list[str], list[str]]:
        original = bullet.strip()
        text = original
        reasons: list[str] = []
        tags: list[str] = []

        for pattern, replacement in FILLER_PATTERNS:
            if pattern.search(text):
                text = pattern.sub(replacement, text)
                if "filler" not in tags:
                    reasons.append("Removed filler that adds length without information.")
                    tags.append("filler")
        text = re.sub(r"\s{2,}", " ", text).strip()

        first = _first_word(text)
        if first in NON_INFLATING_OPENERS:
            # Keep the verb: the fix here is specificity, not a promotion.
            reasons.append(
                f"'{first}' hides what you personally did. Name your own contribution "
                f"(what you designed, wrote or measured) and keep the verb honest - do not "
                f"upgrade a support role into ownership."
            )
            tags.append("specificity")
        elif first in WEAK_OPENERS or first in VERB_UPGRADES:
            replacement = self._pick_verb(text, first)
            text = re.sub(r"^\s*\w+", replacement, text, count=1)
            text = re.sub(r"^(\w+)\s+(?:on|with|for|in)\s+", r"\1 ", text, count=1)
            reasons.append(
                f"Opened with '{first}', which reads as participation rather than ownership; "
                f"'{replacement}' states what you did."
            )
            tags.append("action-verb")
        elif first and first not in ACTION_VERBS and not text[0].isupper():
            text = text[0].upper() + text[1:]

        # Name the technology if the bullet clearly implies work the target
        # cares about but names no tool.
        if not re.search(r"\b(using|with|in)\b", text, re.I) and len(text.split()) > 6:
            text = text.rstrip(". ") + " using <the specific tools you used>"
            reasons.append("The tools used are not named - recruiters and ATS filters both look for them.")
            tags.append("keyword-alignment")

        if not find_metrics(original):
            placeholder = METRIC_PLACEHOLDER_HINTS.get(
                _dominant_category(match), METRIC_PLACEHOLDER_HINTS["default"]
            )
            text = text.rstrip(". ") + ", " + placeholder
            reasons.append(
                "No measurable outcome. Add a number you can defend in interview - never estimate one."
            )
            tags.append("quantify")

        if len(original.split()) > 34:
            reasons.append(
                f"At {len(original.split())} words this bullet is long; consider splitting it in two."
            )
            tags.append("length")

        if not text.endswith((".", "]", ">")):
            text += "."
        return text, reasons, tags

    @staticmethod
    def _pick_verb(text: str, weak: str) -> str:
        if weak in NON_INFLATING_OPENERS:  # defensive - callers already skip these
            return weak.capitalize()
        for pattern, verb in CONTEXT_VERBS:
            if pattern.search(text):
                return verb
        options = VERB_UPGRADES.get(weak)
        return options[0] if options else "Delivered"

    # -- priority actions --------------------------------------------------

    def _priority_actions(
        self, resume: ParsedResume, match: MatchResult, ats: dict[str, Any]
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        req = match.requirement

        for check in ats.get("critical_issues", [])[:3]:
            actions.append(
                {
                    "priority": "high",
                    "type": "ats",
                    "action": check["label"],
                    "detail": check["suggestion"] or check["message"],
                    "effort": "minutes",
                    "honest": True,
                }
            )

        declared_only = [m for m in match.partial() if not m.via]
        if declared_only:
            actions.append(
                {
                    "priority": "high",
                    "type": "presentation",
                    "action": f"Evidence {len(declared_only)} listed skill(s) inside real bullets",
                    "detail": "Skills present: " + ", ".join(m.skill for m in declared_only[:5])
                    + ". This raises your score using experience you already have.",
                    "effort": "under an hour",
                    "honest": True,
                }
            )

        high_gaps = match.missing_by_priority("high")
        if high_gaps:
            actions.append(
                {
                    "priority": "high",
                    "type": "learning",
                    "action": f"Close {len(high_gaps)} blocking skill gap(s)",
                    "detail": (
                        ", ".join(m.skill for m in high_gaps[:5])
                        + f" — treated as hard requirements for {req.company_name} {req.role_title}. "
                        "Build them, then add them."
                    ),
                    "effort": f"about {max(m.learn_weeks for m in high_gaps)} weeks for the longest",
                    "honest": True,
                }
            )

        quantified = match.experience_analysis["quantified_bullets"]
        total = match.experience_analysis["total_bullets"]
        if total and quantified / total < 0.4:
            actions.append(
                {
                    "priority": "medium",
                    "type": "content",
                    "action": "Quantify more bullets with numbers you can defend",
                    "detail": f"{quantified} of {total} bullets currently carry a metric. "
                    "Look back at real dashboards, logs, test reports or commit history for true figures.",
                    "effort": "1-2 hours",
                    "honest": True,
                }
            )

        missing_keywords = match.keyword_analysis["missing"][:4]
        if missing_keywords:
            actions.append(
                {
                    "priority": "medium",
                    "type": "keywords",
                    "action": "Align vocabulary with the target where it is truthful",
                    "detail": "Absent target phrases: " + ", ".join(missing_keywords)
                    + ". Use them only to describe work you genuinely did.",
                    "effort": "30 minutes",
                    "honest": True,
                }
            )
        return actions

    # -- optional LLM path -------------------------------------------------

    def _llm_rewrites(
        self, resume: ParsedResume, match: MatchResult
    ) -> dict[str, list[Suggestion]]:
        bullets = [b for e in resume.experience for b in e.bullets][:6] or resume.bullets[:6]
        if not bullets:
            return {}
        req = match.requirement
        payload = {
            "target": f"{req.company_name} · {req.role_title} · {req.level_title}",
            "target_keywords": req.keywords[:10],
            "matched_skills": [m.skill for m in match.matched()][:15],
            "bullets": bullets,
        }
        system = (
            "You rewrite resume bullets for a specific job target. Absolute rules:\n"
            "1. Never introduce a skill, tool, employer, project or credential not present in the input.\n"
            "2. Never introduce a number, percentage or scale figure. If a metric would help, emit a "
            "bracketed placeholder such as [add measured accuracy].\n"
            "3. Preserve the original meaning exactly; improve verb strength, specificity and structure only.\n"
            "4. Return strict JSON: {\"rewrites\":[{\"original\":\"…\",\"suggested\":\"…\",\"rationale\":\"…\"}]}"
        )
        content = self._call_llm(system, json.dumps(payload, ensure_ascii=False))
        data = _extract_json(content)
        results: list[Suggestion] = []
        for item in data.get("rewrites", [])[:6]:
            original = str(item.get("original", "")).strip()
            suggested = str(item.get("suggested", "")).strip()
            if not original or not suggested:
                continue
            if _introduces_metric(original, suggested):
                continue  # honesty screen: reject fabricated numbers
            results.append(
                Suggestion(
                    section="experience",
                    kind="rewrite",
                    original=original,
                    suggested=suggested,
                    rationale="AI rewrite: " + str(item.get("rationale", "")).strip(),
                    tags=["llm"],
                )
            )
        return {"experience": results}

    def _call_llm(self, system: str, user: str) -> str:
        import requests

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.LLM_MODEL,
                "max_tokens": settings.LLM_MAX_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        return "".join(
            block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedupe(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Collapse suggestions that propose the same rewrite, merging rationales."""
    merged: dict[str, Suggestion] = {}
    for suggestion in suggestions:
        key = suggestion.suggested.strip()
        existing = merged.get(key)
        if existing is None:
            merged[key] = suggestion
            continue
        if suggestion.rationale not in existing.rationale:
            existing.rationale = f"{existing.rationale} {suggestion.rationale}"
        existing.tags = list(dict.fromkeys(existing.tags + suggestion.tags))
    return list(merged.values())


def _weakness_score(bullet: str) -> float:
    score = 0.0
    first = _first_word(bullet)
    if first in WEAK_OPENERS:
        score += 3
    elif first not in ACTION_VERBS:
        score += 1.5
    if not find_metrics(bullet):
        score += 2.5
    if len(bullet.split()) > 34:
        score += 1
    if len(bullet.split()) < 8:
        score += 1
    if any(p.search(bullet) for p, _ in FILLER_PATTERNS):
        score += 1
    return score


def _dominant_category(match: MatchResult) -> str:
    counts: dict[str, int] = {}
    for m in match.matches:
        counts[m.category] = counts.get(m.category, 0) + 1
    return max(counts, key=counts.get) if counts else "default"


def _first_word(text: str) -> str:
    found = re.search(r"[A-Za-z]+", text or "")
    return found.group(0).lower() if found else ""


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?")


def _introduces_metric(original: str, suggested: str) -> bool:
    """True when the rewrite contains a number absent from the original."""
    originals = set(_NUMBER_RE.findall(original))
    for number in _NUMBER_RE.findall(suggested):
        if number not in originals:
            return True
    return False


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


_SERVICE: AIService | None = None


def get_ai_service() -> AIService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = AIService()
    return _SERVICE
