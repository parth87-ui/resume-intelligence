"""Score-scale calibration check across sample resumes and targets."""

import pathlib
import sys

# Resolve the backend package by walking up to the directory holding main.py,
# so these scripts keep working wherever they are run from or moved to.
BACKEND = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "main.py").exists())
SAMPLES = BACKEND.parent / "samples"
sys.path.insert(0, str(BACKEND))
from services.resume_parser import get_resume_parser
from services.analysis_service import get_analysis_service

cases = [
    ("sample_resume.txt", "amazon", "machine-learning-engineer", "entry"),
    ("sample_resume.txt", "google", "data-scientist", "entry"),
    ("sample_resume.txt", "microsoft", "software-engineer", "entry"),
    ("strong_resume.txt", "amazon", "machine-learning-engineer", "mid"),
    ("strong_resume.txt", "amazon", "machine-learning-engineer", "entry"),
    ("strong_resume.txt", "nvidia", "machine-learning-engineer", "mid"),
    ("strong_resume.txt", "netflix", "data-engineer", "mid"),
]
svc = get_analysis_service()
parser = get_resume_parser()
cache = {}
for f, c, r, lvl in cases:
    if f not in cache:
        cache[f] = parser.parse_text((SAMPLES / f).read_text(encoding="utf-8"), f)
    res = svc.analyse_target(cache[f], c, r, lvl)
    s = res["scoring"]
    parts = " ".join(f"{x['label'].split()[0][:4]}={x['score']:.0f}" for x in s["breakdown"])
    print(f"{f[:14]:<15} {c:<10} {r[:22]:<23} {lvl:<7} {s['overall_score']:>5.1f} {s['band']:<18} ATS={res['ats']['score']:>5.1f}  {parts}")
