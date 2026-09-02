"""Career assistant.

Answers questions about a completed analysis. It is grounded: every answer is
built from the analysis payload the user is looking at, so it can cite their
actual numbers instead of giving generic advice.

With ANTHROPIC_API_KEY set it routes through the LLM using the same analysis as
context and the same honesty contract; otherwise it uses intent matching over
the analysis. Both paths refuse to help fabricate credentials.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from config import settings

# "Add AWS experience I don't have", "put Kubernetes on there even though I
# never used it", "list a certification I haven't done" - all the same request.
_ADD_UNOWNED_RE = re.compile(
    r"\b(add|include|put|write|list|say|claim|mention|insert)\b[^?.!]{0,80}?"
    r"\b(?:i\s+)?(?:don'?t|do not|never|haven'?t|have not|didn'?t)\s+"
    r"(?:have|had|use[d]?|do|done|work|worked|know)\b"
)

# "How do I improve this without adding fake experience?" is an *honest* question
# and must not be answered as though the user asked to fabricate, so the honest
# intent is tested first.
INTENTS: list[tuple[str, list[str]]] = [
    ("honest", ["without fake", "without adding fake", "without lying", "without exaggerat",
                 "truthful", "honestly", "genuinely", "ethical", "not lie", "honest way"]),
    ("fabricate", ["fake", "lie about", "make up", "made up", "invent", "pretend",
                    "exaggerate", "pad my resume", "without having", "embellish"]),
    ("score", ["score", "why is my", "compatibility", "match percentage", "rating", "how did you calculate",
                "breakdown", "how am i scored"]),
    ("learn_first", ["learn first", "what should i learn", "which skill", "priority", "start with",
                      "first skill", "where do i start"]),
    ("projects", ["project", "build", "portfolio", "what to make"]),
    ("ats",["ats", "applicant tracking", "resume parse", "formatting", "keyword stuffing", "rejected by system"]),
    ("keywords", ["keyword", "vocabulary", "phrases", "wording", "terms"]),
    ("missing", ["missing", "gap", "what am i lacking", "what do i need", "not have"]),
    ("timeline", ["how long", "timeline", "weeks", "months", "when will i be ready", "roadmap"]),
    ("company", ["culture", "leadership principle", "interview", "screen", "hiring", "bar raiser",
                  "what does the company", "how does"]),
    ("experience", ["experience", "years", "internship", "fresher", "no experience"]),
    ("strengths", ["strength", "what am i good at", "strong", "best part"]),
]


class ChatService:
    def __init__(self) -> None:
        self.llm_enabled = settings.llm_enabled

    # -- public ------------------------------------------------------------

    def answer(self, question: str, analysis: dict[str, Any] | None) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            return self._reply("Ask me anything about your analysis - scores, gaps, projects or timing.", [])

        if analysis is None:
            return self._reply(
                "Run an analysis first (upload a resume and pick a target company and role) and I "
                "can answer using your actual numbers instead of generic advice.",
                ["How does the scoring work?", "What does the ATS score measure?"],
            )

        intent = self._detect_intent(question)

        if self.llm_enabled and intent != "fabricate":
            try:
                return self._llm_answer(question, analysis, intent)
            except Exception:
                pass  # fall through to the grounded rule-based answer

        handler: Callable[[dict[str, Any], str], str] = getattr(self, f"_answer_{intent}", self._answer_default)
        return self._reply(handler(analysis, question), self._followups(analysis, intent), intent)

    # -- intent routing ----------------------------------------------------

    @staticmethod
    def _detect_intent(question: str) -> str:
        lowered = question.lower()
        # A request to *write in* something the user does not have is a
        # fabrication request however politely it is phrased, so it is matched
        # structurally rather than by keyword.
        if _ADD_UNOWNED_RE.search(lowered) and not any(
            phrase in lowered for phrase in ("without", "instead of", "rather than")
        ):
            return "fabricate"
        for intent, triggers in INTENTS:
            if any(trigger in lowered for trigger in triggers):
                return intent
        return "default"

    # -- answers -----------------------------------------------------------

    def _answer_fabricate(self, analysis: dict[str, Any], question: str) -> str:
        gaps = analysis["skill_gap"]["missing_high_priority"][:3]
        names = ", ".join(g["skill"] for g in gaps) or "the skills you are missing"
        projects = analysis.get("project_recommendations") or []
        project_line = (
            f" The fastest honest route is '{projects[0]['title']}' "
            f"({projects[0]['difficulty']}, {projects[0]['estimated_duration']}), which closes "
            f"{', '.join(projects[0]['skills_closed'][:3])}."
            if projects
            else ""
        )
        return (
            "I won't help add skills, projects, employers or credentials you don't have - it fails "
            "technical interviews and reference checks, and it is the fastest way to lose an offer.\n\n"
            f"What I can do is close the gap for real. You're missing {names}."
            f"{project_line}\n\n"
            "There are also legitimate gains available right now: several skills you already have "
            "are hidden in your skills list instead of being demonstrated in a bullet. Fixing that "
            "raises your score without adding a single new claim."
        )

    def _answer_score(self, analysis: dict[str, Any], question: str) -> str:
        scoring = analysis["scoring"]
        target = analysis["target"]
        lines = [
            f"Your overall match for {target['company']['name']} {target['role']['title']} "
            f"({target['level']['title']}) is {scoring['overall_score']:.0f}/100 - {scoring['band']}.",
            "",
            "Here is exactly where it comes from:",
        ]
        for component in sorted(scoring["breakdown"], key=lambda c: -c["contribution"]):
            lines.append(
                f"  • {component['label']}: {component['score']:.0f}/100 "
                f"(weight {component['weight_percent']:.0f}%, contributing "
                f"{component['contribution']:.1f} points) - {component['detail']}"
            )
        lines.extend(["", scoring["narrative"]])
        return "\n".join(lines)

    def _answer_learn_first(self, analysis: dict[str, Any], question: str) -> str:
        plan = analysis.get("skill_priority_plan") or []
        if not plan:
            return "No gaps were detected for this target - your skills already cover the requirement profile."
        lines = ["Learn these in this order - ordered by importance to the target, then by how fast they are to acquire:", ""]
        for item in plan[:6]:
            status = "already listed, needs evidence" if item["status"] == "partial" else "not present"
            lines.append(
                f"  {item['order']}. {item['skill']} ({item['priority']} priority, {status}) - "
                f"about {item['estimated_weeks']} weeks. {item['why']}"
            )
        lines.append("")
        lines.append(
            f"Working sequentially that is roughly {plan[min(5, len(plan)-1)]['cumulative_weeks']} weeks "
            "to the end of this list."
        )
        return "\n".join(lines)

    def _answer_projects(self, analysis: dict[str, Any], question: str) -> str:
        projects = analysis.get("project_recommendations") or []
        if not projects:
            return "No project is needed for this target - your existing evidence already covers the requirements."
        target = analysis["target"]
        lines = [
            f"Ranked by how much of your {target['company']['name']} {target['role']['title']} "
            "gap each one actually closes:",
            "",
        ]
        for project in projects[:3]:
            lines.append(f"  ▸ {project['title']} — {project['difficulty']}, {project['estimated_duration']}")
            lines.append(f"     Closes: {', '.join(project['skills_closed'][:5])}")
            lines.append(f"     Why: {project['rationale']}")
            lines.append(f"     Gap coverage: {project['gap_coverage']:.0f}% of your weighted gap")
            lines.append("")
        lines.append(
            "Add the resume bullet only after the project is finished and you can demo it - "
            "each recommendation includes a bullet template with blanks for your real numbers."
        )
        return "\n".join(lines)

    def _answer_honest(self, analysis: dict[str, Any], question: str) -> str:
        actions = analysis["ai_suggestions"]["priority_actions"]
        honest_now = [a for a in actions if a["type"] in {"presentation", "ats", "content", "keywords"}]
        lines = [
            "Everything below improves your resume using only work you have genuinely done:",
            "",
        ]
        for action in honest_now[:5]:
            lines.append(f"  • {action['action']} ({action['effort']}) - {action['detail']}")
        lines.extend(
            [
                "",
                "The rule this tool follows: optimise the presentation of genuine experience, never "
                "fabricate credentials. Where you are missing something real, the roadmap tells you "
                "how to acquire it rather than how to claim it.",
            ]
        )
        return "\n".join(lines)

    def _answer_ats(self, analysis: dict[str, Any], question: str) -> str:
        ats = analysis["ats"]
        lines = [f"ATS compatibility: {ats['score']:.0f}/100 - {ats['band']}.", ""]
        for family in ats["family_scores"].values():
            lines.append(f"  • {family['label']}: {family['score']:.0f}/100")
        if ats["critical_issues"]:
            lines.extend(["", "Fix these first:"])
            for issue in ats["critical_issues"][:4]:
                lines.append(f"  ✗ {issue['label']} - {issue['suggestion'] or issue['message']}")
        if ats["warnings"]:
            lines.extend(["", "Then these:"])
            for warning in ats["warnings"][:4]:
                lines.append(f"  ! {warning['label']} - {warning['suggestion'] or warning['message']}")
        return "\n".join(lines)

    def _answer_keywords(self, analysis: dict[str, Any], question: str) -> str:
        keywords = analysis["keyword_analysis"]
        target = analysis["target"]
        lines = [
            f"You match {len(keywords['present'])} of {keywords['total']} keywords that recur in "
            f"{target['company']['name']} {target['role']['title']} postings "
            f"({keywords['coverage'] * 100:.0f}% coverage).",
            "",
        ]
        if keywords["present"]:
            lines.append("Present: " + ", ".join(keywords["present"][:10]))
        if keywords["missing"]:
            lines.extend(["", "Absent: " + ", ".join(keywords["missing"][:10])])
        lines.extend(["", keywords["note"]])
        return "\n".join(lines)

    def _answer_missing(self, analysis: dict[str, Any], question: str) -> str:
        gap = analysis["skill_gap"]
        lines = []
        if gap["missing_high_priority"]:
            lines.append("High priority (essential for this role):")
            for item in gap["missing_high_priority"][:6]:
                lines.append(f"  ✗ {item['skill']} - {item['reason']}")
        if gap["missing_medium_priority"]:
            lines.extend(["", "Medium priority (frequently requested):"])
            for item in gap["missing_medium_priority"][:5]:
                lines.append(f"  ○ {item['skill']}")
        if gap["partially_matched"]:
            lines.extend(["", "Partially matched (you have adjacent evidence):"])
            for item in gap["partially_matched"][:5]:
                lines.append(f"  ◐ {item['skill']} - {item['reason']}")
        if gap["emerging"]:
            lines.extend(["", "Emerging (differentiators): " + ", ".join(i["skill"] for i in gap["emerging"][:5])])
        return "\n".join(lines) or "No gaps detected against this target profile."

    def _answer_timeline(self, analysis: dict[str, Any], question: str) -> str:
        roadmap = analysis["learning_roadmap"]
        projection = roadmap["projection"]
        lines = [
            f"Full roadmap for {roadmap['target']}: {roadmap['estimated_completion']} "
            f"({roadmap['total_duration_weeks']} weeks across {len(roadmap['phases'])} phases).",
            "",
        ]
        for phase in roadmap["phases"]:
            lines.append(
                f"  Phase {phase['phase']} — {phase['title']} ({phase['duration_weeks']} weeks): "
                + ", ".join(phase["skills"][:5])
            )
        lines.extend(
            [
                "",
                f"Skills score today: {projection['current_skills_score']:.0f}/100. "
                f"After presentation fixes alone: {projection['after_presentation_fixes']:.0f}/100. "
                f"After closing the high-priority gaps: {projection['after_closing_high_priority']:.0f}/100.",
            ]
        )
        return "\n".join(lines)

    def _answer_company(self, analysis: dict[str, Any], question: str) -> str:
        target = analysis["target"]
        lines = [f"{target['company']['name']} — {target['summary'][:280]}", ""]
        if target.get("values"):
            lines.append("Values they screen for: " + ", ".join(target["values"]))
        if target.get("hiring_signals"):
            lines.extend(["", "What moves the needle on a resume:"])
            for signal in target["hiring_signals"]:
                lines.append(f"  • {signal}")
        if target.get("interview_focus"):
            lines.extend(["", "Interview focus: " + ", ".join(target["interview_focus"])])
        if target.get("screen_notes"):
            lines.extend(["", target["screen_notes"]])
        return "\n".join(lines)

    def _answer_experience(self, analysis: dict[str, Any], question: str) -> str:
        exp = analysis["experience_analysis"]
        lines = [
            f"Detected experience: {exp['detected_years']} year(s) against roughly "
            f"{exp['expected_years']} expected for this level"
            + (f" (gap: {exp['gap_years']} years)." if exp["gap_years"] else "."),
            "",
            f"Relevance of your experience text to the target: {exp['relevance']:.2f} cosine similarity.",
            f"Quantified bullets: {exp['quantified_bullets']} of {exp['total_bullets']}.",
        ]
        if exp["gap_years"] > 0:
            lines.extend(
                [
                    "",
                    "A years gap is not automatically disqualifying. What closes it in practice: "
                    "depth on one substantial project, measurable outcomes, and open-source or "
                    "production evidence a reviewer can check.",
                ]
            )
        return "\n".join(lines)

    def _answer_strengths(self, analysis: dict[str, Any], question: str) -> str:
        scoring = analysis["scoring"]
        best = max(scoring["breakdown"], key=lambda c: c["score"])
        matched = analysis["skill_gap"]["matched"][:8]
        lines = [
            f"Your strongest scoring area is {best['label']} at {best['score']:.0f}/100 - {best['detail']}",
            "",
            "Skills fully evidenced against this target: "
            + ", ".join(m["skill"] for m in matched),
        ]
        extra = analysis["skill_gap"].get("additional_skills") or []
        if extra:
            lines.extend(
                [
                    "",
                    "You also have skills outside this target's profile: "
                    + ", ".join(extra[:8])
                    + ". Keep them, but let the target-relevant ones lead.",
                ]
            )
        return "\n".join(lines)

    def _answer_default(self, analysis: dict[str, Any], question: str) -> str:
        scoring = analysis["scoring"]
        target = analysis["target"]
        insights = analysis.get("insights", [])
        lines = [
            f"For {target['company']['name']} {target['role']['title']} you are at "
            f"{scoring['overall_score']:.0f}/100 ({scoring['band']}).",
            "",
        ]
        for insight in insights[:3]:
            lines.append(f"  • {insight['title']}: {insight['body']}")
        lines.extend(
            [
                "",
                "Ask me things like: why is my score what it is, what should I learn first, "
                "which project helps most, or how do I improve this without adding anything untrue.",
            ]
        )
        return "\n".join(lines)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _followups(analysis: dict[str, Any], intent: str) -> list[str]:
        pool = {
            "score": ["What should I learn first?", "Which project raises my score most?"],
            "learn_first": ["Which project teaches these?", "How long until I am ready?"],
            "projects": ["How long is the full roadmap?", "What are my blocking gaps?"],
            "missing": ["Which project closes these gaps?", "What can I fix today without learning anything?"],
            "ats": ["What keywords am I missing?", "How is my overall score calculated?"],
            "timeline": ["Which project should I start with?", "What are my strengths?"],
        }
        return pool.get(
            intent,
            [
                "Why is my score what it is?",
                "What should I learn first?",
                "How do I improve this without adding fake experience?",
            ],
        )

    @staticmethod
    def _reply(answer: str, followups: list[str], intent: str = "default") -> dict[str, Any]:
        return {
            "answer": answer,
            "intent": intent,
            "suggested_questions": followups,
            "grounded": intent != "default" or bool(answer),
        }

    # -- LLM path ----------------------------------------------------------

    def _llm_answer(self, question: str, analysis: dict[str, Any], intent: str) -> dict[str, Any]:
        import json

        import requests

        context = {
            "target": analysis["target"]["company"]["name"] + " " + analysis["target"]["role"]["title"],
            "level": analysis["target"]["level"]["title"],
            "overall_score": analysis["scoring"]["overall_score"],
            "band": analysis["scoring"]["band"],
            "breakdown": [
                {"area": c["label"], "score": c["score"], "weight": c["weight_percent"], "detail": c["detail"]}
                for c in analysis["scoring"]["breakdown"]
            ],
            "matched_skills": [m["skill"] for m in analysis["skill_gap"]["matched"]][:20],
            "partial_skills": [
                {"skill": m["skill"], "reason": m["reason"]}
                for m in analysis["skill_gap"]["partially_matched"]
            ][:10],
            "missing_high": [m["skill"] for m in analysis["skill_gap"]["missing_high_priority"]],
            "missing_medium": [m["skill"] for m in analysis["skill_gap"]["missing_medium_priority"]],
            "ats_score": analysis["ats"]["score"],
            "top_projects": [
                {"title": p["title"], "closes": p["skills_closed"], "weeks": p["duration_weeks"]}
                for p in analysis.get("project_recommendations", [])[:3]
            ],
            "roadmap_weeks": analysis["learning_roadmap"]["total_duration_weeks"],
        }
        system = (
            "You are a career assistant grounded in a resume analysis. Rules:\n"
            "1. Answer only from the supplied analysis context; never invent numbers or facts.\n"
            "2. Never advise adding skills, experience, projects or credentials the candidate does "
            "not have. If asked to, refuse and redirect to acquiring the skill honestly.\n"
            "3. Be specific and concise. Cite the candidate's own numbers.\n"
            "4. Plain text, no markdown headings."
        )
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.LLM_MODEL,
                "max_tokens": 900,
                "system": system,
                "messages": [
                    {
                        "role": "user",
                        "content": f"ANALYSIS CONTEXT:\n{json.dumps(context, ensure_ascii=False)}\n\nQUESTION: {question}",
                    }
                ],
            },
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        text = "".join(
            block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
        ).strip()
        if not text:
            raise RuntimeError("empty LLM response")
        return {
            "answer": text,
            "intent": intent,
            "suggested_questions": self._followups(analysis, intent),
            "grounded": True,
            "engine": "llm",
        }


_CHAT: ChatService | None = None


def get_chat_service() -> ChatService:
    global _CHAT
    if _CHAT is None:
        _CHAT = ChatService()
    return _CHAT
