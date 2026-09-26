# Resume Intelligence

[![Live demo](https://img.shields.io/badge/live%20demo-open%20app-6366f1?style=for-the-badge)](https://resume-intelligence-iq3x.onrender.com)
[![API docs](https://img.shields.io/badge/API-swagger%20docs-22d3ee?style=for-the-badge)](https://resume-intelligence-iq3x.onrender.com/docs)
[![Python](https://img.shields.io/badge/python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![spaCy](https://img.shields.io/badge/spaCy-NLP-09A3D5?style=for-the-badge)](https://spacy.io/)
[![Tests](https://img.shields.io/badge/tests-142%20passing-22c55e?style=for-the-badge)](backend/tests/)

**AI-powered company-specific resume optimisation and career intelligence.**
Developed by **Parth Khandelwal**.

Upload a resume, pick a target company and role, and get an explainable
compatibility score, an apply/don't-apply verdict, a prioritised skill-gap
analysis, ATS diagnostics, truthful rewrite suggestions, gap-driven project
recommendations, a phased learning roadmap — and a rebuilt resume that is
re-scored through the same pipeline to prove the improvement.

### ▶ [Try it live](https://resume-intelligence-iq3x.onrender.com)

> Hosted on a free tier, so the first request after a quiet spell takes
> **40–60 seconds** while the instance wakes and loads the spaCy model. It is
> not broken — give it a moment. Every request after that is fast.

```
resume upload → parsing → NLP skill extraction → company + role target
   → requirement composition → matching → weighted scoring → fit verdict
   → ATS analysis → AI suggestions → project recommendations → roadmap
   → rebuilt resume, re-parsed and re-scored
```

---

## Quick start

```bash
pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
python run.py
```

Then open **http://127.0.0.1:8000/** — the dashboard, API and database all run
from that one command. Interactive API docs are at `/docs`.

```bash
python run.py --check     # verify the environment, report optional components
python run.py --seed      # create and seed the database, then exit
python run.py --port 9000 # different port
pytest backend/tests -q   # 142 tests (needs backend/requirements-dev.txt)
```

Two sample resumes are included for trying it immediately:

```bash
python samples/make_samples.py   # also renders PDF and DOCX versions
```

`samples/sample_resume.txt` is a realistic student resume; `strong_resume.txt`
is a mid-level ML engineer. Analysing both against Amazon → Machine Learning
Engineer is the fastest way to see the scoring discriminate.

### Requirements

Python 3.10+. Everything else installs from `backend/requirements.txt`.
The app degrades gracefully rather than failing:

| Component | If missing |
|---|---|
| spaCy model | Falls back to a regex NLP pipeline (same API, lower recall) |
| scikit-learn | Falls back to a NumPy TF-IDF/cosine implementation |
| PyMuPDF | Falls back to pdfplumber for PDF extraction |
| python-docx | DOCX upload is rejected with a clear message; PDF/TXT still work |
| `ANTHROPIC_API_KEY` | Uses the deterministic rewrite engine (the default) |

---

## What it actually does

### 1. Resume parsing

PDF, DOCX and plain text in; structured JSON out — contact block, sections,
dated experience entries with their bullets, projects with their tech lines,
education with degree and field, certifications and achievements.

Real documents fight back, so the parser handles what actually breaks:
PDF ligatures (`ﬁ`, `ﬂ`, `ﬃ` are single glyphs and silently defeat every
match), smart quotes, blank lines used as spacing inside one job, `Tech:` and
`Link:` metadata lines, and four different date formats.

### 2. NLP skill extraction

144 canonical skills with aliases, matched with word boundaries and
lemmatisation so "deployed", "deploying" and "deploys" all resolve. Every hit
records **where** it was found and the sentence it came from, which is what
makes the next step possible.

### 3. Evidence, not keywords

The core idea. Listing "Docker" in a skills list is not the same as describing
something you containerised, so each match carries a credit:

| Evidence | Credit |
|---|---|
| Applied in an experience or project bullet | **1.00** |
| Declared in the skills section only | **0.80** |
| Adjacent — a directly related skill is applied | **0.35** |
| No evidence anywhere | **0.00** |

### 4. Company-specific requirements

Requirements are **composed, never enumerated**. Nine companies × ten roles ×
four levels is 360 targets; writing 360 profiles by hand would be
unmaintainable and would break the moment a tenth company was added.

```
role baseline          required/preferred/optional with importance 0-1
  + company profile    focus skills raise importance, may promote tier
  + curated override   hand-written refinements for 12 key combinations
  + experience level   importance scaling + weight redistribution
  = JobRequirement
```

A new company automatically works with all ten roles; a new role automatically
works with all nine companies.

### 5. Explainable scoring

Six components, each scored separately and reported with its own method,
evidence and reasoning. The weights shift with the level you picked:

| Component | Intern | Entry | Mid | Senior |
|---|---|---|---|---|
| Skills match | 35% | 35% | 35% | 32% |
| Keyword alignment | 20% | 20% | 20% | 18% |
| Experience relevance | 5% | 10% | 15% | 25% |
| Project relevance | 25% | 20% | 15% | 10% |
| Education & certifications | 10% | 8% | 5% | 3% |
| Semantic similarity | 5% | 7% | 10% | 12% |

Read sideways: an intern is judged on projects, a senior on experience. Bands
run Early Stage → Developing → Moderate → Strong → Excellent, and the raw
TF-IDF rescaling is stated in the output rather than hidden.

### 6. Fit verdict — should you apply?

A different question from the score, and the one a candidate asks first. A
resume can score 62/100 and still be an automatic rejection, because a weighted
average dilutes a fatal gap across five things going well. So independent
checks run alongside the score and **any one of them can veto the verdict**:

| Check | Knockout when |
|---|---|
| Required-skill coverage | Below 40% of the role's required skills |
| Experience | **Only** when the posting states a number and the gap is ≥ 2 years |
| Degree | The posting requires a Master's or PhD and the resume shows neither |
| Blocking gaps · overall score | Never — they inform the verdict, they do not veto it |

The experience rule carries a deliberate distinction: a target picked from the
catalogue carries **our** estimate of expected years, so it can only warn; a
pasted posting that says "6+ years" is **the employer's** bar, so it can knock
you out. When a knockout applies, the advice addresses that rather than bullet
polish — rewording sentences while a hard filter excludes you is wasted effort.

### 7. Section scores

The weighted score says which *dimension* is weak. This says which *part of the
document* is weak, which is what you actually edit — summary, skills,
experience, projects and education each scored from their own checks.

### 8. ATS analysis

16 point-weighted checks across four families — parsability, structure, content
and keywords — each returning a pass/warn/fail with a specific fix.

### 9. Truthful AI suggestions

Section-by-section rewrites under the honesty contract below, each labelled
`SUGGESTED REWRITE — verify before using`, with bracketed placeholders where a
metric belongs.

### 10. Resume builder

Generates a corrected resume, then **re-parses its own output and scores it
again through the identical pipeline**, so the before → after number is
measured rather than claimed.

Bullets go through the same rewrite rules as the suggestions engine; the summary
is assembled only from facts already in the document. Skills the resume does not
evidence are added **only** where you tick "I have this"; anything marked as in
progress goes on a separate `Currently learning:` line and never into the skills
list.

Exports to DOCX, PDF or TXT — single column, black text, no tables or images, so
an ATS parses it cleanly.

### 11. Job description analysis

Paste a real posting and it is parsed into required/preferred skills,
responsibilities, keywords and any stated degree requirement, then run through
the identical pipeline — on its own, or fused with a curated company profile.

**Non-technical postings are refused rather than scored.** Everything this
platform knows is technical, so a sales or nursing posting would produce a
confident number that measured nothing. A posting is rejected only when it names
fewer than three technical skills *and* uses more non-technical than technical
vocabulary, so a genuine ML posting mentioning "customer support" still passes.

### 12. Projects and roadmap

Projects are ranked by how much of *your* importance-weighted gap they close,
then sequenced into phases: surface what you already have → close blocking gaps
→ prove it with a project → broaden → emerging skills. The projected score uses
the same formula as the live score.

### 13. Grounded career assistant

Answers questions using your actual analysis ("Why is my score what it is?",
"What should I learn first?"). It refuses to help fabricate credentials and
redirects to acquiring the skill instead.

---

## The honesty contract

> **Optimise the presentation of genuine experience, but never fabricate
> credentials or achievements.**

Enforced in code, not just in prompt text:

1. **No invented skills, employers, projects, certifications or dates.**
2. **No invented metrics.** Where a number would strengthen a bullet, the engine
   emits `[add a measurable result — e.g. accuracy/F1 change, dataset size]`.
   The optional LLM path is additionally screened: any rewrite containing a
   number absent from the original is discarded (`_introduces_metric`).
3. **No inflated contribution.** "Helped the team…" is never rewritten to
   "Led the team…". Support verbs are in a `NON_INFLATING_OPENERS` set that the
   verb-upgrade rules refuse to touch; the suggestion asks you to be *specific*
   about your own contribution instead.
4. **Missing skills get a route, not a line to paste.** Bad: "Add AWS
   experience." Good: "If you have used AWS, name the services explicitly. If
   not, build *Deploy an End-to-End ML Model on AWS* (4 weeks) and add it after
   you finish it."
5. **Every rewrite is labelled for verification.**

`TestHonestyGuarantees` and `TestBuilderHonesty` assert all of this against real
generated output — including that the resume builder never emits a number absent
from the source document. The builder's summary states a years figure only when
the resume states one itself; a duration inferred from date ranges is accurate
but was never *claimed* by the candidate, so it is not written back out.

### Two deliberate exceptions

People will add unproven things to a resume with or without a tool. Two paths
exist for that, both opt-in, both labelled, and neither ever the default.

**`auto_add` mode** adds every missing required and preferred skill at once.
This bypasses rule 1. It is constrained rather than hidden: `confirmed` mode is
the default and an unrecognised mode falls back to it; every added skill is
returned in `auto_added_skills` with a warning and recorded in the change log;
the UI states the consequence before you choose it and disables the per-skill
ticks so the choice is unambiguous.

**Adding a recommended project.** The builder will not write a project you have
not built. Instead it names the projects that would close your gaps, with the
bullet to use *after* you finish one, and lets you tick:

* **"I built this"** — inserts that bullet as a *scaffold* with its `<blanks>`
  intact, never as a finished claim;
* **"Building it"** — adds a separate, labelled `In progress:` line that cannot
  read as finished work.

A scaffold is not a claim, and the export enforces that: **`<…>` blanks block
the download.** Stripping them would turn

> Deployed a `<model type>` model … at `<latency>` ms p95

into "Deployed a model … at ms p95" — a broken sentence that also asserts work
that may never have happened. `[add a measurable result …]` prompts still strip
silently, because removing one leaves a sentence that is still true.

Rules 2–5 hold in every mode: no invented metrics, no inflated contribution, no
fabricated employers, projects or dates.

---

## Architecture

```
Browser dashboard  →  FastAPI  →  services  →  ml  →  SQLite / PostgreSQL
                                      ↓
                              datasets/*.json
```

The API layer contains no analysis logic: every route validates input, calls a
service and returns the result. The whole engine runs from a test or a script
with no web server involved.

```
project/
├── run.py                       # launcher: --check, --seed, --port
├── .env.example
├── backend/
│   ├── main.py                  # FastAPI app, middleware, static mount
│   ├── config.py                # settings from the environment
│   ├── schemas.py               # pydantic request/response models
│   ├── requirements.txt         # runtime only
│   ├── requirements-dev.txt     # + pytest and httpx
│   ├── api/routes/              # catalog · resume · analysis · builder · chat
│   ├── services/
│   │   ├── knowledge_base.py    # dataset loading + requirement composition
│   │   ├── resume_parser.py     # PDF/DOCX/TXT → structured JSON
│   │   ├── skill_extractor.py   # ontology matching with evidence
│   │   ├── job_matcher.py       # gap analysis + component scores
│   │   ├── fit_evaluator.py     # apply/don't-apply verdict + knockouts
│   │   ├── ats_analyzer.py      # 16 ATS checks
│   │   ├── section_scorer.py    # per-section scores with their working
│   │   ├── ai_service.py        # rewrites (rule-based + optional LLM)
│   │   ├── resume_builder.py    # generates and re-scores a new resume
│   │   ├── resume_export.py     # DOCX / PDF / TXT rendering
│   │   ├── recommendation_engine.py
│   │   ├── jd_parser.py         # pasted job descriptions + the tech gate
│   │   ├── chat_service.py      # grounded assistant
│   │   └── analysis_service.py  # orchestrates the pipeline
│   ├── ml/
│   │   ├── nlp_pipeline.py      # spaCy with a regex fallback
│   │   ├── similarity_model.py  # TF-IDF + cosine, NumPy fallback
│   │   └── scoring_engine.py    # weighted score + bands
│   ├── datasets/                # JSON source of truth
│   ├── db/                      # SQLAlchemy models, session, seeding
│   └── tests/                   # 142 tests + manual scripts
├── frontend/                    # build-free ES modules, hand-built SVG charts
├── docs/                        # API.md · ARCHITECTURE.md · DATASETS.md
└── samples/
```

### Datasets

| File | Entries | Holds |
|---|---|---|
| `skills.json` | 144 | Ontology: category, aliases, related skills, weeks to learn |
| `roles.json` | 10 | Role baselines, independent of employer |
| `companies.json` | 9 | Company profiles and what each emphasises |
| `projects.json` | 22 | Projects with skills taught and a resume bullet template |
| `experience_levels.json` | 4 | Intern → Senior, each redistributing the weights |
| `company_role_overrides.json` | 12 | Hand-tuned refinements for key combinations |

### Database

SQLite by default, PostgreSQL-ready through `DATABASE_URL`. JSON datasets are
the source of truth; the database mirrors them for queryability and stores
analyses. `init_db()` is idempotent — it creates tables and upserts reference
data on every startup.

### Frontend

No build step. `index.html` loads `src/app.js` as an ES module; the app is a
hash router over page modules, each exposing `render(state)` and
`mount(root, ctx)`. Charts are hand-built SVG driven by the same design tokens
as the rest of the UI. Light and dark are one token layer, and all rendered
content passes through `esc()` so parsed resume text can never inject markup.

---

## API

Full interactive documentation at `/docs`. Summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status, active NLP backend, dataset counts |
| GET | `/api/catalog` | Companies, roles, levels, weights |
| GET | `/api/catalog/skills` | The skill ontology (filterable) |
| GET | `/api/catalog/scoring` | Scoring formula, weights, credit rules, bands |
| GET | `/api/catalog/requirements/{company}/{role}?level=` | Composed requirement profile |
| POST | `/api/resume/upload` | Multipart upload → parsed resume + `resume_id` |
| POST | `/api/resume/parse-text` | Same, from pasted text |
| GET | `/api/resume/{id}` | Stored parsed resume |
| POST | `/api/analyze` | Full company/role analysis |
| POST | `/api/analyze/job-description` | Analysis against a pasted posting |
| GET | `/api/analysis/{id}` | Stored analysis |
| GET | `/api/analyses` | Recent analyses |
| POST | `/api/resume/build` | Generate an improved resume from a stored analysis |
| POST | `/api/resume/export` | Download it as DOCX, PDF or TXT |
| POST | `/api/projects/recommend` | Projects for an explicit skill list |
| GET | `/api/roadmap/{analysis_id}` | Roadmap for a stored analysis |
| POST | `/api/chat` | Grounded career assistant |

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"resume_id": 1, "company": "amazon",
       "role": "machine-learning-engineer", "level": "entry"}'
```

See [docs/API.md](docs/API.md) for payload shapes, the `fit_assessment` block
and every error code.

---

## Extending it

Adding a company, role, skill or project means editing JSON — no analysis code
changes. See [docs/DATASETS.md](docs/DATASETS.md) for the schemas.

```jsonc
// backend/datasets/companies.json
{
  "id": "stripe",
  "name": "Stripe",
  "tagline": "Financial infrastructure, correctness first.",
  "values": ["Rigour", "User focus", "Move with urgency"],
  "focus_skills": [
    { "skill": "Go", "boost": 0.3, "promote_to": "required" },
    { "skill": "System Design", "boost": 0.2 },
    { "skill": "Testing", "boost": 0.15 }
  ],
  "keywords": ["idempotency", "financial correctness", "API design"],
  "hiring_signals": ["Evidence of correctness under failure, not just happy paths"],
  "screen_notes": "Stripe weights API design and testing discipline more than most.",
  "interview_focus": ["API design", "Failure modes", "Testing strategy"]
}
```

`boost` raises that skill's importance on top of the role baseline;
`promote_to` can move it into a higher tier. Restart, and Stripe works with all
ten roles at all four levels.

---

## Configuration

Copy `.env.example` to `.env`. Every value has a working default.

| Variable | Default | Notes |
|---|---|---|
| `DEBUG` | `false` (`true` via `run.py`) | Auto-reload, verbose errors, no-cache static assets |
| `PORT` | `8000` | Injected by most hosting platforms |
| `HOST` | `127.0.0.1` | Must be `0.0.0.0` in a container |
| `DATABASE_URL` | SQLite file | Set a `postgresql+psycopg://` URL to persist data |
| `CORS_ORIGINS` | `*` | Restrict to your frontend origin when deployed |
| `CORS_ORIGIN_REGEX` | *(empty)* | For deploy previews |
| `WEB_CONCURRENCY` | `1` | Each worker loads its own ~350 MB of models |
| `MAX_UPLOAD_MB` | `10` | Also check your platform's own request limit |
| `STORE_UPLOADED_FILES` | `false` | Keep off: only extracted text is stored |
| `ANTHROPIC_API_KEY` | *(empty)* | Enables generative rewrites |

---

## Running it elsewhere

`python run.py` serves the dashboard, the API and the docs from one process, so
anything that can run Python can host it:

```bash
pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
DEBUG=false HOST=0.0.0.0 PORT=8000 python -m uvicorn main:app --app-dir backend
```

Set `DEBUG=false` (the default) so exception detail is never returned in
responses, and `CORS_ORIGINS` to your frontend origin if you host the two halves
separately. Allow ~400 MB of RAM per worker — each one loads its own copy of the
spaCy model and scikit-learn.

---

## Testing

```bash
pip install -r backend/requirements-dev.txt   # pytest + httpx, once
pytest backend/tests -q                    # 142 tests
pytest backend/tests -q -k Honesty         # the fabrication guarantees
python backend/tests/manual/calibrate.py   # score scale across targets
python backend/tests/manual/smoke.py       # full pipeline, printed
python backend/tests/manual/api_check.py   # HTTP checks against a running server
python backend/tests/manual/edge_cases.py  # adversarial resume sweep
```

| File | Covers |
|---|---|
| `test_pipeline.py` | Datasets, parsing, extraction, credit rules, scoring bounds, ATS, section scores, honesty guarantees, JD parsing, every API error path |
| `test_fit_and_builder.py` | The tech-domain gate, fit verdicts and knockouts, both builder consent modes, export renderers |
| `test_parsing_regressions.py` | Bugs found against a real resume — ligatures, entry grouping, technical fields, builder idempotence, user-selected projects |

The bug that matters in a scoring tool is not the one that crashes — it is the
one that returns a confident, wrong number. The suite is built around catching
exactly that:

* **Honesty tests** assert the contract against real generated output.
* **Idempotence tests** rebuild a generated resume three times and require the
  result to stop changing. This caught a compounding bug where every rebuild
  appended another placeholder and split every bullet into its own project.
* **Adversarial parsing** throws twelve deliberately broken resumes at the
  pipeline — no headings, headings with no content, keyword stuffing, unicode,
  four date formats, 2,000 words, markup injection — and requires a usable
  result or a clear typed error, never a stack trace.
* **Calibration** re-scores seven known resume-target pairs against recorded
  numbers, so a refactor that silently moves scores is caught immediately.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `NLP: regex` in the footer | The spaCy model is missing — `python -m spacy download en_core_web_sm` |
| DOCX upload rejected | `pip install python-docx` |
| "No recognisable technical skills" on a JD | The requirements section was not included in the paste |
| A posting returns `422 non_tech_jd` | It is not a technical role; the platform only scores software, data, ML and cloud roles |
| Export refuses with "blanks still need your own details" | A `<…>` blank is unfilled — fill it or delete the line; this is deliberate |
| Frontend changes do not appear | Bump the `?v=` query on the asset links in `frontend/index.html` |
| Scores all zero | The resume text extracted empty — check `warnings` in the upload response |
