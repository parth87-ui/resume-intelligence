"""Resume builder.

Generates a new resume from the parsed original plus the analysis, then
re-scores its own output against the same requirement so the improvement is
measured rather than claimed.

What it will and will not do
----------------------------
The honesty contract applies here more sharply than anywhere else, because this
module writes the document rather than suggesting edits to it:

* Bullets are rewritten through :meth:`AIService._rewrite_bullet` - the same
  filler-removal and verb-upgrade rules used by the suggestion engine, with
  ``NON_INFLATING_OPENERS`` protected, so "helped the team" is never promoted
  into "led the team".
* Metric placeholders stay as ``[add a measurable result …]``. No number ever
  enters the output that was not in the input.
* The summary is assembled only from facts already in the resume: the target
  role, detected years, skills that were actually found, and real project names.

Skills the resume does *not* evidence are added only when the user says so:

``confirmed`` (default)
    Adds only the skills ticked in ``confirmed_skills``.
``auto_add``
    Adds every missing required and preferred skill, returns them in
    ``auto_added_skills`` with a warning, and is never the default. This is the
    one path that can put an unevidenced skill on the page, which is why it is
    an explicit opt-in and labelled in the output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ml.scoring_engine import ScoringEngine
from services.ai_service import get_ai_service
from services.fit_evaluator import get_fit_evaluator
from services.job_matcher import MatchResult, get_job_matcher
from services.knowledge_base import JobRequirement, get_knowledge_base
from services.recommendation_engine import get_recommendation_engine
from services.resume_parser import ParsedResume, get_resume_parser
from services.skill_extractor import get_skill_extractor

MODE_CONFIRMED = "confirmed"
MODE_AUTO_ADD = "auto_add"
MODES = (MODE_CONFIRMED, MODE_AUTO_ADD)

AUTO_ADD_WARNING = (
    "These skills were added without your confirmation. "
    "Remove any you can't defend in an interview."
)

ADDED_PROJECT_WARNING = (
    "You said you have built this. The bullet is a scaffold with blanks, not a "
    "finished claim - fill in your own numbers. It cannot be exported until you do."
)

IN_PROGRESS_LABEL = "In progress"

# Ontology categories collapsed into the groups a reader expects on a resume.
SKILL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Languages", ("language",)),
    ("ML & AI", ("ml",)),
    ("Frameworks & Libraries", ("framework", "library")),
    ("Data", ("data",)),
    ("Cloud & DevOps", ("cloud", "devops")),
    ("Databases", ("database",)),
    ("Tools", ("tool",)),
    ("CS Fundamentals", ("cs",)),
)
OTHER_GROUP = "Other"

CONTACT_FIELDS = ("name", "email", "phone", "linkedin", "github", "portfolio", "location")
CONTACT_LABELS = {
    "name": "Full name",
    "email": "Email address",
    "phone": "Phone number",
    "linkedin": "LinkedIn URL",
    "github": "GitHub URL",
    "portfolio": "Portfolio or personal site",
    "location": "City and country",
}
# Which of those are worth chasing: a portfolio is genuinely optional.
ESSENTIAL_CONTACT = ("name", "email", "phone")

_PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]|<[^>]+>")
# The parser keeps "Tech: ..." as an ordinary bullet; the builder regenerates
# that line itself, so the original is dropped rather than rewritten twice.
_TECH_LINE_RE = re.compile(
    r"^\s*(?:tech(?:nolog(?:y|ies))?|stack|tools|built\s+with)\s*[:\-]", re.IGNORECASE
)
# A line that is only a repo or demo URL is a link, not an achievement -
# rewriting it into a bullet produces "Github.com/..., [add a measurable result]".
_LINK_ONLY_RE = re.compile(
    r"^\s*(?:link|repo|demo|url)?\s*[:\-]?\s*(?:https?://|www\.|github\.com/|gitlab\.com/)\S+\s*$", re.IGNORECASE
)


@dataclass
class BuildOptions:
    mode: str = MODE_CONFIRMED
    confirmed_skills: list[str] = field(default_factory=list)
    learning_skills: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)
    # Recommended-project ids the user says they have actually built, and ones
    # they are part-way through. Both are opt-in and neither is a default.
    projects_built: list[str] = field(default_factory=list)
    projects_in_progress: list[str] = field(default_factory=list)

    def normalised_mode(self) -> str:
        return self.mode if self.mode in MODES else MODE_CONFIRMED


class ResumeBuilder:
    """Rebuilds a resume against a specific target."""

    def __init__(self) -> None:
        self.kb = get_knowledge_base()
        self.extractor = get_skill_extractor()
        self.matcher = get_job_matcher()
        self.parser = get_resume_parser()
        self.ai = get_ai_service()
        self.fit = get_fit_evaluator()
        self.recommender = get_recommendation_engine()

    # -- public ------------------------------------------------------------

    def build(
        self,
        resume: ParsedResume,
        requirement: JobRequirement,
        options: BuildOptions | None = None,
    ) -> dict[str, Any]:
        options = options or BuildOptions()
        mode = options.normalised_mode()

        before_skills = self.extractor.extract(resume)
        before_match = self.matcher.match(resume, before_skills, requirement)
        before_report = ScoringEngine(requirement.weights).score(before_match.components)
        before_fit = self.fit.evaluate(resume, before_match, before_report)

        added = self._resolve_added_skills(before_match, mode, options)
        learning = self._canonical_list(options.learning_skills)
        changes: list[dict[str, str]] = []

        contact, missing_details = self._contact(resume, options.details, changes)
        summary = self._summary(resume, before_match, added, changes)
        skill_groups = self._skill_groups(resume, before_match, added, learning, changes)
        experience = self._experience(resume, before_match, changes)
        projects = self._projects(resume, before_match, changes)
        added_projects, in_progress = self._selected_projects(options, changes)
        projects += added_projects
        education = self._education(resume)
        certifications = list(resume.certifications)
        achievements = list(resume.achievements)

        structured = {
            "contact": contact,
            "summary": summary,
            "skills": skill_groups,
            "learning": learning,
            "experience": experience,
            "projects": projects,
            "projects_in_progress": in_progress,
            "education": education,
            "certifications": certifications,
            "achievements": achievements,
        }
        text = self._render_text(structured)

        after = self._rescore(text, requirement)
        if mode == MODE_AUTO_ADD and added["auto_added"]:
            changes.append(
                {
                    "section": "Skills",
                    "action": f"Auto-added {len(added['auto_added'])} unconfirmed skill(s)",
                    "detail": AUTO_ADD_WARNING,
                }
            )

        return {
            "resume": structured,
            "text": text,
            "changes": changes,
            "missing_details": missing_details,
            "placeholder_count": len(_PLACEHOLDER_RE.findall(text)),
            "mode": mode,
            "skills_added": {
                "confirmed": added["confirmed"],
                "auto_added": added["auto_added"],
                "learning": learning,
            },
            "auto_added_skills": added["auto_added"],
            "projects_added": {
                "built": [p["name"] for p in added_projects],
                "in_progress": [p["title"] for p in in_progress],
            },
            "added_project_warning": ADDED_PROJECT_WARNING if added_projects else "",
            # Blanks the user must supply before the document can be exported.
            "unfilled_blanks": _required_blank_count(text),
            "auto_add_warning": AUTO_ADD_WARNING if added["auto_added"] else "",
            "score": {
                "before": round(before_report.overall, 1),
                "after": round(after["report"].overall, 1),
                "fit_before": before_fit["verdict"],
                "fit_after": after["fit"]["verdict"],
                "band_before": before_report.band,
                "band_after": after["report"].band,
            },
            # Projects are the one gap the builder cannot close for you. It will
            # not write a project you have not built, so it names the ones worth
            # building instead - with the bullet to use once you have.
            "recommended_projects": [
                {
                    "id": project["id"],
                    "title": project["title"],
                    "description": project["description"],
                    "difficulty": project["difficulty"],
                    "estimated_duration": project["estimated_duration"],
                    "skills_closed": project["skills_closed"],
                    "resume_bullet_template": project["resume_bullet_template"],
                }
                for project in self.recommender.recommend_projects(before_match, limit=3)
            ],
            "projects_note": (
                "These are not in the generated resume, and will not be: writing a project "
                "you have not built is the one thing this tool refuses to do. Build one, then "
                "paste its bullet in - the template keeps the blanks so the numbers stay yours."
            ),
            "verification_note": (
                "Every bracketed blank is deliberate - fill it with a real number or tool "
                "you can defend. Nothing in this document was invented for you."
            ),
        }

    # -- skills ------------------------------------------------------------

    def _resolve_added_skills(
        self, match: MatchResult, mode: str, options: BuildOptions
    ) -> dict[str, list[str]]:
        """Which unevidenced skills end up on the page, and on whose authority."""
        missing = {
            m.skill
            for m in match.matches
            if m.status == "missing" and m.tier in {"required", "preferred"}
        }
        if mode == MODE_AUTO_ADD:
            return {"confirmed": [], "auto_added": sorted(missing)}

        # Confirmed mode: only what the user ticked, and only if it was
        # genuinely one of their gaps.
        confirmed = [
            name for name in self._canonical_list(options.confirmed_skills) if name in missing
        ]
        return {"confirmed": sorted(set(confirmed)), "auto_added": []}

    def _canonical_list(self, names: Iterable[str]) -> list[str]:
        out: list[str] = []
        for raw in names or []:
            canonical = self.kb.canonical_skill(raw) or raw.strip()
            if canonical and canonical not in out:
                out.append(canonical)
        return out

    def _skill_groups(
        self,
        resume: ParsedResume,
        match: MatchResult,
        added: dict[str, list[str]],
        learning: list[str],
        changes: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        detected = [s.name for s in self.extractor.extract(resume) if s.category != "soft"]
        claimed = added["confirmed"] + added["auto_added"]

        # A skill being "learned" must not also appear as a skill you have.
        learning_set = set(learning)
        everything = [
            name for name in dict.fromkeys(detected + claimed) if name not in learning_set
        ]

        required_first = {
            m.skill for m in match.matches if m.tier == "required"
        }

        grouped: list[dict[str, Any]] = []
        placed: set[str] = set()
        for label, categories in SKILL_GROUPS:
            members = [
                name for name in everything if self.kb.category_of(name) in categories
            ]
            if not members:
                continue
            # Requirement skills lead each line: a recruiter scanning for the
            # posting's vocabulary should hit it first.
            members.sort(key=lambda n: (n not in required_first, n.lower()))
            placed.update(members)
            grouped.append({"label": label, "skills": members})

        # Terms the candidate listed that the ontology does not know. They are
        # still real skills - dropping them would lose information.
        extras = [
            term.strip()
            for term in resume.skill_section_terms
            if term.strip()
            and self.kb.canonical_skill(term) is None
            and len(term.strip()) > 1
            and term.strip() not in learning_set
        ]
        if extras:
            grouped.append({"label": OTHER_GROUP, "skills": sorted(set(extras))[:12]})

        if grouped:
            changes.append(
                {
                    "section": "Skills",
                    "action": f"Regrouped into {len(grouped)} labelled categories",
                    "detail": (
                        "Skills are grouped and the target's required skills lead each line, "
                        "so both a human skim and a keyword filter find them."
                    ),
                }
            )
        if added["confirmed"]:
            changes.append(
                {
                    "section": "Skills",
                    "action": f"Added {len(added['confirmed'])} skill(s) you confirmed",
                    "detail": ", ".join(added["confirmed"])
                    + " - you ticked these, so make sure each is defensible.",
                }
            )
        if learning:
            changes.append(
                {
                    "section": "Skills",
                    "action": f"{len(learning)} skill(s) marked as in progress",
                    "detail": (
                        "Listed on a separate 'Currently learning' line, never mixed into the "
                        "skills you already have."
                    ),
                }
            )
        return grouped

    def _selected_projects(
        self, options: BuildOptions, changes: list[dict[str, str]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Projects the user explicitly chose to put on the page.

        This is the second place the tool will write something the resume did
        not already evidence, and the riskier one - a skill is a word, a
        project is a story an interviewer will dig into. So the bullet goes in
        as a *scaffold*: the template keeps its <...> blanks, the export
        refuses to run until they are filled, and nothing here invents a
        number. A project the user is only part-way through is kept separate
        and labelled, never mixed in with finished work.
        """
        built: list[dict[str, Any]] = []
        for project in self._lookup_projects(options.projects_built):
            built.append(
                {
                    "name": project["title"],
                    "description": "",
                    "bullets": [project.get("resume_bullet_template", "").strip()],
                    "tech": [
                        self.kb.canonical_skill(skill) or skill
                        for skill in project.get("skills_taught", [])[:8]
                    ],
                    "link": "",
                    "added_by_user": True,
                }
            )

        in_progress = [
            {
                "title": project["title"],
                "duration": f"{project.get('duration_weeks', 0)} weeks",
            }
            for project in self._lookup_projects(options.projects_in_progress)
        ]

        if built:
            changes.append(
                {
                    "section": "Projects",
                    "action": f"Added {len(built)} project(s) you confirmed you built",
                    "detail": ADDED_PROJECT_WARNING,
                }
            )
        if in_progress:
            changes.append(
                {
                    "section": "Projects",
                    "action": f"Listed {len(in_progress)} project(s) as in progress",
                    "detail": (
                        "Shown on a separate line and labelled, so it never reads as "
                        "finished work."
                    ),
                }
            )
        return built, in_progress

    def _lookup_projects(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        wanted = [i for i in dict.fromkeys(ids or []) if i]
        if not wanted:
            return []
        by_id = {p["id"]: p for p in self.kb.projects}
        return [by_id[i] for i in wanted if i in by_id]

    # -- sections ----------------------------------------------------------

    def _contact(
        self, resume: ParsedResume, details: dict[str, str], changes: list[dict[str, str]]
    ) -> tuple[dict[str, str], list[dict[str, str]]]:
        contact: dict[str, str] = {}
        supplied: list[str] = []
        for field_name in CONTACT_FIELDS:
            override = (details or {}).get(field_name, "").strip()
            existing = (resume.contact.get(field_name) or "").strip()
            contact[field_name] = override or existing
            if override and override != existing:
                supplied.append(field_name)

        missing = [
            {"field": name, "label": CONTACT_LABELS[name], "essential": name in ESSENTIAL_CONTACT}
            for name in CONTACT_FIELDS
            if not contact[name]
        ]
        if supplied:
            changes.append(
                {
                    "section": "Header",
                    "action": f"Filled in {len(supplied)} contact field(s)",
                    "detail": ", ".join(CONTACT_LABELS[f] for f in supplied) + ".",
                }
            )
        return contact, missing

    def _summary(
        self,
        resume: ParsedResume,
        match: MatchResult,
        added: dict[str, list[str]],
        changes: list[dict[str, str]],
    ) -> list[str]:
        """Two or three lines, every clause traceable to something already true."""
        role = match.requirement.role_title
        # Only a figure the resume states itself may be written back out. The
        # matcher's detected_years is inferred from date ranges - accurate, but
        # writing "0.8 year(s)" would put a number on the page that the
        # candidate never claimed, which is exactly what rule 2 forbids.
        declared = float(resume.metadata.get("declared_years_experience") or 0)

        required_names = [
            m.skill for m in match.matches if m.tier == "required" and m.status == "matched"
        ]
        other_matched = [
            m.skill
            for m in match.matches
            if m.status == "matched" and m.skill not in required_names
        ]
        headline_skills = (required_names + other_matched)[:5]

        lines: list[str] = []
        if declared >= 1:
            opener = f"{role} with {declared:g}+ years of hands-on experience"
        elif resume.experience:
            opener = f"{role} with hands-on industry and project experience"
        else:
            opener = f"Aspiring {role} with hands-on project experience"
        if headline_skills:
            opener += " in " + _join(headline_skills)
        lines.append(opener + ".")

        names = [p.name for p in resume.projects if p.name][:2]
        roles = [e.organisation or e.title for e in resume.experience if e.organisation or e.title][:2]
        if names:
            lines.append("Project work includes " + _join(names) + ".")
        elif roles:
            lines.append("Experience across " + _join(roles) + ".")

        claimed = added["confirmed"] + added["auto_added"]
        if claimed:
            lines.append("Additionally works with " + _join(claimed[:4]) + ".")

        changes.append(
            {
                "section": "Professional summary",
                "action": "Rewritten around this target",
                "detail": (
                    f"Names the {role} target and leads with the skills the posting requires. "
                    "Built only from facts already in your resume - no metrics invented."
                ),
            }
        )
        return lines

    def _experience(
        self, resume: ParsedResume, match: MatchResult, changes: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        rewritten = 0
        for entry in resume.experience:
            bullets: list[str] = []
            for bullet in entry.bullets:
                new, _reasons, _tags = self.ai._rewrite_bullet(bullet, match)
                if new.strip() != bullet.strip():
                    rewritten += 1
                bullets.append(new)
            entries.append(
                {
                    "title": entry.title,
                    "organisation": entry.organisation,
                    "date_range": entry.date_range,
                    "bullets": bullets,
                }
            )
        if rewritten:
            changes.append(
                {
                    "section": "Experience",
                    "action": f"Tightened {rewritten} bullet(s)",
                    "detail": (
                        "Filler removed and weak openers replaced with action verbs. Support verbs "
                        "like 'helped' were left alone on purpose - they are not upgraded into "
                        "ownership you did not have."
                    ),
                }
            )
        return entries

    def _projects(
        self, resume: ParsedResume, match: MatchResult, changes: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        tech_lines = 0
        for project in resume.projects:
            source_bullets, link = [], ""
            for bullet in project.bullets:
                if _TECH_LINE_RE.match(bullet):
                    continue
                if _LINK_ONLY_RE.match(bullet):
                    link = link or bullet.strip().lstrip("-").strip()
                    continue
                source_bullets.append(bullet)
            bullets = [self.ai._rewrite_bullet(b, match)[0] for b in source_bullets]
            # The tech line comes only from this project's own text, so a skill
            # never migrates from one project to another.
            tech = [
                name
                for name in self.extractor.extract_from_text(project.raw)
                if self.kb.category_of(name) != "soft"
            ]
            if tech:
                tech_lines += 1
            entries.append(
                {
                    "name": project.name,
                    "description": _useful_description(
                        project.description, source_bullets, project.name
                    ),
                    "bullets": bullets,
                    "tech": tech[:10],
                    "link": link,
                }
            )
        if tech_lines:
            changes.append(
                {
                    "section": "Projects",
                    "action": f"Added a Tech: line to {tech_lines} project(s)",
                    "detail": (
                        "Each line lists only the tools named in that project's own text - "
                        "nothing carried over from elsewhere in the resume."
                    ),
                }
            )
        return entries

    @staticmethod
    def _education(resume: ParsedResume) -> list[dict[str, str]]:
        entries = []
        for item in resume.education:
            head = ", ".join(p for p in (item.degree, item.field_of_study) if p)
            tail = ", ".join(p for p in (item.institution, item.year) if p)
            line = " — ".join(p for p in (head, tail) if p) or item.raw.strip()
            if item.score:
                line = f"{line} | {item.score}"
            entries.append(
                {
                    "line": line,
                    "degree": item.degree,
                    "field": item.field_of_study,
                    "institution": item.institution,
                    "year": item.year,
                    "score": item.score,
                }
            )
        return entries

    # -- rendering ---------------------------------------------------------

    def _render_text(self, data: dict[str, Any]) -> str:
        out: list[str] = []
        contact = data["contact"]

        if contact.get("name"):
            out.append(contact["name"].upper())
        line = " | ".join(
            contact[f] for f in ("email", "phone", "location", "linkedin", "github", "portfolio")
            if contact.get(f)
        )
        if line:
            out.append(line)

        if data["summary"]:
            out += ["", "PROFESSIONAL SUMMARY"] + data["summary"]

        if data["skills"] or data["learning"]:
            out += ["", "TECHNICAL SKILLS"]
            for group in data["skills"]:
                out.append(f"{group['label']}: {', '.join(group['skills'])}")
            if data["learning"]:
                out.append(f"Currently learning: {', '.join(data['learning'])}")

        if data["experience"]:
            out += ["", "EXPERIENCE"]
            for entry in data["experience"]:
                header = " | ".join(
                    p for p in (entry["title"], entry["organisation"], entry["date_range"]) if p
                )
                # No placeholder header. Writing a literal "Experience" line
                # makes the document unparseable by our own parser, which then
                # reads it as another entry on the next pass.
                if header:
                    out.append(header)
                out += [f"- {b}" for b in entry["bullets"]]
                out.append("")
            if out and out[-1] == "":
                out.pop()

        if data["projects"]:
            out += ["", "PROJECTS"]
            for project in data["projects"]:
                if project["name"]:
                    out.append(project["name"])
                if project["description"]:
                    out.append(project["description"])
                out += [f"- {b}" for b in project["bullets"]]
                if project["tech"]:
                    out.append(f"Tech: {', '.join(project['tech'])}")
                if project.get("link"):
                    out.append(f"Link: {project['link']}")
                out.append("")
            if data.get("projects_in_progress"):
                # Labelled, and last, so it can never read as finished work.
                titles = ", ".join(
                    f"{p['title']} ({p['duration']})" for p in data["projects_in_progress"]
                )
                out.append(f"{IN_PROGRESS_LABEL}: {titles}")
                out.append("")
            if out and out[-1] == "":
                out.pop()

        if data["education"]:
            out += ["", "EDUCATION"] + [e["line"] for e in data["education"]]

        if data["certifications"]:
            out += ["", "CERTIFICATIONS"] + [f"- {c}" for c in data["certifications"]]

        if data["achievements"]:
            out += ["", "ACHIEVEMENTS"] + [f"- {a}" for a in data["achievements"]]

        return "\n".join(out).strip() + "\n"

    # -- scoring -----------------------------------------------------------

    def _rescore(self, text: str, requirement: JobRequirement) -> dict[str, Any]:
        """Run the generated document back through the identical pipeline."""
        reparsed = self.parser.parse_text(text, filename="generated-resume.txt")
        skills = self.extractor.extract(reparsed)
        match = self.matcher.match(reparsed, skills, requirement)
        report = ScoringEngine(requirement.weights).score(match.components)
        return {
            "report": report,
            "fit": self.fit.evaluate(reparsed, match, report),
            "match": match,
        }


def _required_blank_count(text: str) -> int:
    """Blanks the user still has to fill before the document can be exported."""
    from services.resume_export import required_blanks

    return len(required_blanks(text))

def _useful_description(description: str, bullets: list[str], name: str = "") -> str:
    """Keep a project description only when it adds something the bullets don't.

    For many layouts the parser's description field is the whole project block,
    which would print the bullets a second time and drag the tech list and repo
    link along with it.
    """
    text = (description or "").strip()
    if not text or len(text.split()) > 25 or _TECH_LINE_RE.search(text):
        return ""
    if name and text.lower() == name.strip().lower():
        return ""  # printing the project name twice helps nobody
    opening = " ".join(text.lower().split()[:5])
    if any(opening and opening in bullet.lower() for bullet in bullets):
        return ""
    return text


def _join(items: list[str]) -> str:
    """Oxford-free list join: 'a, b and c'."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


_BUILDER: ResumeBuilder | None = None


def get_resume_builder() -> ResumeBuilder:
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = ResumeBuilder()
    return _BUILDER
