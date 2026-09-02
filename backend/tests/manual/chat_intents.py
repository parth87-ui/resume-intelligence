"""Intent routing checks for the career assistant."""

import pathlib
import sys

# Resolve the backend package by walking up to the directory holding main.py,
# so these scripts keep working wherever they are run from or moved to.
BACKEND = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "main.py").exists())
SAMPLES = BACKEND.parent / "samples"
sys.path.insert(0, str(BACKEND))
from services.chat_service import get_chat_service
svc = get_chat_service()
cases = [
    ("Can you add AWS experience I don't have to my resume?", "fabricate"),
    ("Just put Kubernetes on there even though I never used it", "fabricate"),
    ("Add a certification I haven't done", "fabricate"),
    ("Can you make up a project for me?", "fabricate"),
    ("How can I improve my resume without adding fake experience?", "honest"),
    ("What can I do truthfully to improve?", "honest"),
    ("Why is my Amazon compatibility score low?", "score"),
    ("What skills should I learn first?", "learn_first"),
    ("Which project will improve my ML Engineer profile?", "projects"),
    ("What am I missing for this role?", "missing"),
    ("How long until I am ready?", "timeline"),
    ("Is my resume ATS friendly?", "ats"),
    ("What keywords am I missing?", "keywords"),
    ("How does Amazon screen candidates?", "company"),
    ("How many years of experience do I have?", "experience"),
    ("What are my strengths?", "strengths"),
]
bad = 0
for q, expected in cases:
    got = svc._detect_intent(q)
    flag = "ok " if got == expected else "FAIL"
    if got != expected: bad += 1
    print(f"{flag} {got:<12} (want {expected:<12}) {q}")
print(("\nALL PASS" if not bad else f"\n{bad} FAILURES"))
sys.exit(1 if bad else 0)
