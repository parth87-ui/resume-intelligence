"""Manual smoke test of the full pipeline (not pytest)."""

import pathlib
import sys

# Resolve the backend package by walking up to the directory holding main.py,
# so these scripts keep working wherever they are run from or moved to.
BACKEND = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "main.py").exists())
SAMPLES = BACKEND.parent / "samples"
sys.path.insert(0, str(BACKEND))
import json

from services.resume_parser import get_resume_parser
from services.analysis_service import get_analysis_service

text = pathlib.Path(__file__).resolve().parents[2] / "samples" / "sample_resume.txt"
parsed = get_resume_parser().parse_text(text.read_text(encoding="utf-8"), "sample_resume.txt")

print("== CONTACT =="); print(json.dumps(parsed.contact, indent=1))
print("== SECTIONS =="); print(parsed.metadata["sections_detected"])
print("== META =="); print({k:v for k,v in parsed.metadata.items() if k not in ("warnings",)})
print("warnings:", parsed.metadata["warnings"])
print("== EXPERIENCE ==")
for e in parsed.experience: print(" -", e.title, "|", e.organisation, "|", e.date_range, "|", e.duration_months, "mo |", len(e.bullets), "bullets")
print("== PROJECTS ==")
for p in parsed.projects: print(" -", p.name, "|", len(p.bullets), "bullets | tech:", p.tech_hint[:40])
print("== EDUCATION ==")
for e in parsed.education: print(" -", e.degree, "|", e.institution, "|", e.year, "|", e.score)
print("== CERTS ==", parsed.certifications)
print("== SKILL TERMS ==", parsed.skill_section_terms[:15])

res = get_analysis_service().analyse_target(parsed, "amazon", "machine-learning-engineer", "entry")
print("\n== SCORE ==", res["scoring"]["overall_score"], res["scoring"]["band"])
for c in res["scoring"]["breakdown"]:
    print(f"   {c['label']:<28} {c['score']:>5.1f}  w={c['weight_percent']}%  {c['detail'][:70]}")
print("== ATS ==", res["ats"]["score"], res["ats"]["band"])
g = res["skill_gap"]
print("MATCHED:", [m["skill"] for m in g["matched"]])
print("PARTIAL:", [(m["skill"], m["via"]) for m in g["partially_matched"]])
print("MISSING HIGH:", [m["skill"] for m in g["missing_high_priority"]])
print("MISSING MED:", [m["skill"] for m in g["missing_medium_priority"]])
print("OPTIONAL:", [m["skill"] for m in g["optional"]])
print("EMERGING:", [m["skill"] for m in g["emerging"]])
print("== PROJECTS RECOMMENDED ==")
for p in res["project_recommendations"][:3]: print(" -", p["title"], p["fit_score"], p["skills_closed"])
print("== ROADMAP ==", res["learning_roadmap"]["estimated_completion"], [ph["title"] for ph in res["learning_roadmap"]["phases"]])
print("== AI SUGGESTIONS ==")
for sec, items in res["ai_suggestions"]["sections"].items():
    for i in items[:2]:
        print(f" [{sec}] {i['original'][:60]!r}\n     -> {i['suggested'][:110]!r}")
print("== INSIGHTS ==")
for i in res["insights"]: print(" *", i["title"])
