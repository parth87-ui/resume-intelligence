"""Adversarial resume sweep.

Throws deliberately awkward documents at the full pipeline and reports what
breaks. Every case must either produce a usable analysis or a clear, typed
error - never a stack trace and never a 500.

    python backend/tests/manual/edge_cases.py
"""

from __future__ import annotations

import pathlib
import sys
import time
import traceback

# Resolve the backend package by walking up to the directory holding main.py,
# so these scripts keep working wherever they are run from or moved to.
BACKEND = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "main.py").exists())
SAMPLES = BACKEND.parent / "samples"
sys.path.insert(0, str(BACKEND))

from services.analysis_service import get_analysis_service  # noqa: E402
from services.resume_parser import ResumeParsingError, get_resume_parser  # noqa: E402

CASES: dict[str, str] = {
    "no headings at all": (
        "Priya Nair priya@example.com. I am a developer who has built things with python "
        "and sql for two years at a startup. I like solving problems and want to work at a "
        "big company. I know some machine learning and have used pandas a lot for analysis "
        "of customer data and reporting to managers every week without fail."
    ),
    "headings only, no content": (
        "SUMMARY\n\nSKILLS\n\nEXPERIENCE\n\nPROJECTS\n\nEDUCATION\n\nCERTIFICATIONS\n"
    ),
    "single line": "John Smith - Software Engineer - john@example.com",
    "no contact details": (
        "TECHNICAL SKILLS\nPython, Java, SQL, Docker, Kubernetes, AWS\n\n"
        "EXPERIENCE\nSoftware Engineer | Some Company | 2020 - 2023\n"
        "- Built microservices handling 10k requests per second\n"
        "- Reduced deployment time by 60% through CI/CD automation\n\n"
        "EDUCATION\nB.Sc Computer Science, 2020\n"
    ),
    "keyword stuffed": (
        "SKILLS\n" + ("Python machine learning AWS Docker Kubernetes " * 40) + "\n\n"
        "EXPERIENCE\nEngineer | Corp | 2021 - 2024\n- Python machine learning AWS Docker\n"
    ),
    "unicode and emoji": (
        "Zoë Müller-O'Brien 🚀\nzoe@example.com | +49 30 12345678\n\n"
        "SKILLS\n• Python ▸ TensorFlow ▸ PyTorch\n• Deutsch (Muttersprache) — Englisch (C2)\n\n"
        "EXPERIENCE\nML Engineer | Beispiel GmbH | Jan 2021 – Dez 2023\n"
        "- Trainierte Modelle mit PyTorch und erreichte 94% Genauigkeit\n"
        "- Deployed models to AWS with Docker → 40% latency reduction\n\n"
        "EDUCATION\nM.Sc. Informatik, Technische Universität München, 2020\n"
    ),
    "dates in every format": (
        "SKILLS\nPython, SQL\n\nEXPERIENCE\n"
        "Analyst | A Corp | 01/2020 - 12/2021\n- Did analysis with Python\n"
        "Analyst | B Corp | Jan 2022 to Present\n- Did more analysis with SQL\n"
        "Analyst | C Corp | 2018-2019\n- Did earlier analysis on spreadsheets\n"
        "Analyst | D Corp | Mar '17 - Nov '18\n- Did the earliest analysis of all\n"
    ),
    "very long": (
        "SKILLS\nPython, SQL, AWS\n\nEXPERIENCE\nEngineer | Corp | 2015 - 2024\n"
        + "".join(
            f"- Delivered project number {i} using Python and SQL improving throughput by {i}%\n"
            for i in range(1, 160)
        )
    ),
    "html escape attempt": (
        "<script>alert('xss')</script> Bob Tables\nbob@example.com\n\n"
        "SKILLS\nPython, <img src=x onerror=alert(1)>, SQL\n\n"
        "EXPERIENCE\nDev | \"Quotes\" & <Angles> Inc | 2020 - 2023\n"
        "- Built a parser that handles <tags> & 'quotes' correctly\n"
    ),
    "numbers everywhere": (
        "SKILLS\nPython 3.11, Java 17, PostgreSQL 15\n\nEXPERIENCE\n"
        "Engineer | Corp | 2020 - 2024\n"
        "- Processed 1,234,567 records across 42 pipelines at 99.99% uptime for $1.2M savings\n"
    ),
    "whitespace soup": "   \n\n\t\t  \n   Ana  Lee   ana@x.com \n\n\n\n\t SKILLS \n\n  Python  \n\n\n",
    "repeated section headings": (
        "EXPERIENCE\nDev | A | 2020 - 2021\n- Built things with Python\n\n"
        "EXPERIENCE\nDev | B | 2021 - 2022\n- Built more things with SQL\n\n"
        "SKILLS\nPython, SQL\n"
    ),
}

TARGETS = [
    ("amazon", "machine-learning-engineer", "entry"),
    ("google", "software-engineer", "senior"),
    ("netflix", "data-engineer", "mid"),
]

def main() -> int:
    parser = get_resume_parser()
    service = get_analysis_service()
    failures = 0

    print(f"{'case':<28} {'words':>5} {'sect':>4} {'skills':>6} {'score':>6} {'ats':>5}  {'ms':>5}  status")
    print("-" * 96)

    for name, text in CASES.items():
        company, role, level = TARGETS[hash(name) % len(TARGETS)]
        started = time.perf_counter()
        try:
            parsed = parser.parse_text(text, f"{name}.txt")
            result = service.analyse_target(parsed, company, role, level)
            elapsed = (time.perf_counter() - started) * 1000

            score = result["scoring"]["overall_score"]
            ats = result["ats"]["score"]
            skills = result["resume_overview"]["skill_profile"]["total"]
            sections = len(parsed.metadata["sections_detected"])
            problems = []
            if not 0 <= score <= 100:
                problems.append(f"score out of range: {score}")
            if not 0 <= ats <= 100:
                problems.append(f"ats out of range: {ats}")
            if not result["scoring"]["breakdown"]:
                problems.append("empty breakdown")
            if result["learning_roadmap"]["total_duration_weeks"] < 0:
                problems.append("negative roadmap duration")

            status = "ok" if not problems else "PROBLEM: " + "; ".join(problems)
            if problems:
                failures += 1
            print(
                f"{name:<28} {parsed.metadata['words']:>5} {sections:>4} {skills:>6} "
                f"{score:>6.1f} {ats:>5.1f} {elapsed:>6.0f}  {status}"
            )
        except ResumeParsingError as exc:
            print(f"{name:<28} {'-':>5} {'-':>4} {'-':>6} {'-':>6} {'-':>5} {'-':>6}  handled: {exc}")
        except Exception:
            failures += 1
            print(f"{name:<28} {'!':>5} {'!':>4} {'!':>6} {'!':>6} {'!':>5} {'!':>6}  CRASH")
            traceback.print_exc()

    print("-" * 96)
    print("all cases handled" if not failures else f"{failures} case(s) need attention")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
