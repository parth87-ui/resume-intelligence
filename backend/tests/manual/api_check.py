"""End-to-end API check against a running server."""

import pathlib
import sys

# Resolve the backend package by walking up to the directory holding main.py,
# so these scripts keep working wherever they are run from or moved to.
BACKEND = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "main.py").exists())
SAMPLES = BACKEND.parent / "samples"
sys.path.insert(0, str(BACKEND))
import json

BASE = "http://127.0.0.1:8077"

def req(method, path, data=None, headers=None, raw=None):
    url = BASE + path
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    h = headers or ({"Content-Type": "application/json"} if data is not None else {})
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def multipart(path, filename, content, field="file"):
    boundary = "----check123"
    parts = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
             f"Content-Type: text/plain\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return req("POST", path, raw=parts, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

ok = lambda c: "OK " if 200 <= c < 300 else "ERR"

s, health = req("GET", "/api/health"); print(ok(s), "health", health["status"], health["datasets"], health["nlp_backend"]["backend"])
s, cat = req("GET", "/api/catalog"); print(ok(s), "catalog", len(cat["companies"]), "companies", len(cat["roles"]), "roles", cat["skill_count"], "skills")
s, sc = req("GET", "/api/catalog/scoring"); print(ok(s), "scoring methodology keys:", list(sc.keys()))
s, rq = req("GET", "/api/catalog/requirements/amazon/machine-learning-engineer?level=entry")
print(ok(s), "requirements: curated =", rq["curated"], "| required:", [x["skill"] for x in rq["required_skills"][:6]])

s, up = multipart("/api/resume/upload", "sample_resume.txt", (SAMPLES/"sample_resume.txt").read_bytes())
print(ok(s), "upload ->", "resume_id" in up and up.get("resume_id"), up.get("contact", {}).get("name"), "| skills:", len(up.get("skills_detected", [])))
rid = up.get("resume_id")

s, an = req("POST", "/api/analyze", {"resume_id": rid, "company": "amazon", "role": "machine-learning-engineer", "level": "entry"})
print(ok(s), "analyze ->", an.get("scoring", {}).get("overall_score"), an.get("scoring", {}).get("band"), "| analysis_id:", an.get("analysis_id"))
aid = an.get("analysis_id")

s, err = req("POST", "/api/analyze", {"resume_id": rid, "company": "nosuchco", "role": "machine-learning-engineer"})
print(ok(s) if s == 404 else "ERR", "unknown company ->", s, err.get("detail", "")[:60])

s, err = req("POST", "/api/analyze", {"resume_id": 99999, "company": "amazon", "role": "machine-learning-engineer"})
print("OK " if s == 404 else "ERR", "unknown resume ->", s, err.get("detail", "")[:50])

s, err = req("POST", "/api/analyze", {"company": "amazon", "role": "machine-learning-engineer"})
print("OK " if s == 400 else "ERR", "no resume ->", s, err.get("detail", "")[:60])

s, badf = multipart("/api/resume/upload", "resume.exe", b"binary junk here")
print("OK " if s == 415 else "ERR", "bad extension ->", s, badf.get("detail", "")[:60])

jd = """Machine Learning Engineer at Amazon
Basic Qualifications:
- 3+ years of experience with Python and machine learning
- Experience with AWS, Docker and model deployment in production
- Strong SQL and data pipeline skills
Preferred Qualifications:
- Experience with Amazon SageMaker and MLOps practices
- Familiarity with Apache Spark and Kubernetes
Responsibilities:
- Build and deploy machine learning models that serve millions of customers
- Own model monitoring and retraining pipelines end to end
- Partner with science teams to move research into production
"""
s, jdres = req("POST", "/api/analyze/job-description", {"resume_id": rid, "job_description": jd, "level": "mid"})
print(ok(s), "JD analyze ->", jdres.get("scoring", {}).get("overall_score"),
      "| detected:", jdres.get("job_description_analysis", {}).get("detected_company"),
      "/", jdres.get("job_description_analysis", {}).get("detected_role"),
      "| required:", [x["skill"] for x in jdres.get("job_description_analysis", {}).get("required_skills", [])][:6])

s, fused = req("POST", "/api/analyze/job-description", {"resume_id": rid, "job_description": jd, "company": "amazon", "role": "machine-learning-engineer", "level": "entry"})
print(ok(s), "JD fused ->", fused.get("scoring", {}).get("overall_score"), "| fused:", fused.get("job_description_analysis", {}).get("fused_with_company_profile"))

for q in ["Why is my Amazon compatibility score low?", "What skills should I learn first?",
          "Can you add AWS experience I don't have to my resume?", "Which project will improve my profile?"]:
    s, chat = req("POST", "/api/chat", {"question": q, "analysis_id": aid})
    print(ok(s), f"chat[{chat.get('intent')}] {q[:38]!r} ->", chat.get("answer", "")[:88].replace("\n", " "))

s, projs = req("POST", "/api/projects/recommend", {"missing_skills": ["AWS", "Docker", "MLOps"], "role": "machine-learning-engineer", "company": "amazon"})
print(ok(s), "projects ->", [p["title"][:40] for p in projs["projects"][:3]])

s, road = req("GET", f"/api/roadmap/{aid}"); print(ok(s), "roadmap ->", road["roadmap"]["estimated_completion"], len(road["roadmap"]["phases"]), "phases")
s, lst = req("GET", "/api/analyses"); print(ok(s), "analyses stored:", len(lst))
s, got = req("GET", f"/api/analysis/{aid}"); print(ok(s), "fetch analysis ->", got["scoring"]["overall_score"])
s, doc = req("GET", "/openapi.json"); print(ok(s), "openapi paths:", len(doc["paths"]))
