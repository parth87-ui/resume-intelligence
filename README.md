# Resume Intelligence

**Developed by Parth Khandelwal**

**AI-powered company-specific resume optimisation and career intelligence.**

Upload a resume, pick a target company and role, and get an explainable
compatibility score, a prioritised skill-gap analysis, ATS diagnostics,
truthful rewrite suggestions, gap-driven project recommendations and a phased
learning roadmap — built for that specific target, not generic advice.

```
Resume upload → parsing → NLP skill extraction → company + role target
   → requirement analysis → similarity & matching → gap detection
   → ATS analysis → AI suggestions → project recommendations → learning roadmap
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
pytest backend/tests -q   # 64 tests (needs backend/requirements-dev.txt)
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
| `ANTHROPIC_API_KEY` | Uses the deterministic rewrite engine (the default) |

---

## What it actually does

### 1. Resume parsing
PDF (PyMuPDF → pdfplumber fallback), DOCX (python-docx, including tables) and
TXT are converted to structured JSON: contact details, section segmentation,
dated work experience with durations, projects, education with degree/field/
institution/year, certifications, achievements and the raw skills block.

### 2. NLP skill extraction
A **144-skill ontology** with aliases drives detection, and the extractor
records *where* each skill was found — because location changes meaning:

| Evidence | Credit |
|---|---|
| Applied in an experience or project bullet | 100% |
| Listed in the skills section only | 80% |
| Only an adjacent, related skill is present | 35% |
| Not evidenced anywhere | 0% |

Ambiguous names are matched case-sensitively with tight boundaries, so
`go-to-market`, `R&D` and `C-level` never register as programming languages,
while `Languages: C, R, Go` and aliases like `golang` still do.

### 3. Company-specific requirements
Requirements are **composed**, never hardcoded:

```
role baseline  →  company profile  →  experience level  →  curated override
```

The same Machine Learning Engineer role produces a different requirement set at
Amazon (AWS promoted to *required*, SageMaker and ownership weighted up) than at
NVIDIA (CUDA and C++ promoted to *required*). 12 company × role combinations
carry hand-curated overrides; every other combination is still fully supported
because it composes from the role and company files.

### 4. Explainable scoring
Six weighted components, each traceable to its evidence:

| Component | Default weight | Measured by |
|---|---|---|
| Skills match | 35% | Importance-weighted coverage of required/preferred/optional skills |
| Keyword alignment | 20% | Share of company/role keywords evidenced (partial matches count half) |
| Experience relevance | 15% | Detected years + cosine relevance + quantified-bullet ratio |
| Project relevance | 15% | Weighted skill overlap, depth and measured outcomes |
| Education & certifications | 5% | Degree relevance and certification evidence |
| Semantic similarity | 10% | TF-IDF cosine + skill-graph expansion |

`overall = Σ (component_score × weight) ÷ Σ weights`

Weights shift with the selected experience level, so a student is not penalised
on the same experience axis as a senior hire. The API returns the formula, the
weights, every component's method and the evidence behind each number —
see `GET /api/catalog/scoring`.

### 5. Section scores
The weighted score says which *dimension* is weak; section scores say which
*part of the document* to edit. Summary, skills, experience, projects and
education are each scored 0-100 from their own checks, every one showing its
points and reason - "Contains generic filler: passionate", "3 listed skills
appear in no bullet", "1 of 2 projects state a measurable result".

### 6. ATS analysis
16 deterministic checks across four families — parsability, structure, content
and keywords — each worth a stated number of points, producing a 0–100 score
with the exact reason for every point lost.

### 7. Truthful AI suggestions
Section-by-section rewrites under a hard honesty contract (below), each labelled
`SUGGESTED REWRITE — verify before using`, with bracketed placeholders where a
metric belongs.

### 8. Projects and roadmap
Projects are ranked by how much of *your* importance-weighted gap they close,
then sequenced into phases: surface what you already have → close blocking gaps
→ prove it with a project → broaden → emerging skills. The projected score uses
the same formula as the live score, so the number is defensible.

### 9. Job description analysis
Paste a real posting and it is parsed into required/preferred skills,
responsibilities and keywords, then run through the identical pipeline — on its
own, or fused with a curated company profile.

### 10. Grounded career assistant
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

`TestHonestyGuarantees` in the test suite asserts all of this against real
generated output.

---

## Architecture

```
Browser dashboard  →  FastAPI  →  services  →  ml  →  SQLite / PostgreSQL
                                      ↓
                              datasets/*.json
```

```
project/
├── run.py                       # launcher: --check, --seed, --port
├── .env.example
├── backend/
│   ├── main.py                  # FastAPI app, middleware, static mount
│   ├── config.py                # settings from the environment
│   ├── schemas.py               # pydantic request/response models
│   ├── requirements.txt
│   ├── api/routes/              # catalog, resume, analysis, chat
│   ├── services/
│   │   ├── knowledge_base.py    # dataset loading + requirement composition
│   │   ├── resume_parser.py     # PDF/DOCX/TXT → structured JSON
│   │   ├── skill_extractor.py   # ontology matching with evidence
│   │   ├── job_matcher.py       # gap analysis + component scores
│   │   ├── ats_analyzer.py      # 16 ATS checks
│   │   ├── section_scorer.py    # per-section scores with their working
│   │   ├── ai_service.py        # rewrite engine (rule-based + optional LLM)
│   │   ├── recommendation_engine.py  # projects + roadmap
│   │   ├── jd_parser.py         # pasted job descriptions
│   │   ├── chat_service.py      # grounded assistant
│   │   └── analysis_service.py  # pipeline orchestration
│   ├── ml/
│   │   ├── nlp_pipeline.py      # spaCy with a regex fallback
│   │   ├── similarity_model.py  # TF-IDF + cosine, keyword coverage
│   │   └── scoring_engine.py    # weighted, explainable scoring
│   ├── db/                      # SQLAlchemy models, session, seeding
│   ├── datasets/                # companies, roles, skills, projects, levels
│   ├── models/                  # persisted ML artefacts (optional)
│   └── tests/
├── frontend/
│   ├── index.html
│   ├── dev/contrast-audit.js    # WCAG audit, run from the browser console
│   └── src/{app.js, components/, pages/, services/, styles/}
├── docs/{ARCHITECTURE.md, API.md, SCORING.md, DATASETS.md}
└── samples/
```

**Theming.** The interface ships in a bright light palette, with a dark option
behind the ☾/☀ toggle in the top bar (remembered in `localStorage`). Every colour
in the app - including the SVG charts - resolves through design tokens defined
once in `frontend/src/styles/design-system.css`: the light palette on `:root`,
the dark overrides on `[data-theme="dark"]`. No component hardcodes a colour, so
switching themes is a single attribute change and adding a third palette means
adding one token block.

**Contrast.** Both palettes pass WCAG AA (4.5:1 body text, 3:1 large text) on
every page. That is measured, not assumed - `frontend/dev/contrast-audit.js`
walks the live DOM, composites each translucent ancestor to find the effective
background, and reports anything below the threshold:

```js
// paste frontend/dev/contrast-audit.js into the browser console, then:
await contrastAudit.runBothThemes();
```

Token values were chosen from that measurement rather than by eye - several
pairs that looked fine failed, including a few inherited from the original dark
theme.

**Frontend note.** The dashboard is a build-free ES-module single-page app with
hand-built SVG charts (gauge, donut, radar, bars), served directly by FastAPI.
This is a deliberate deviation from the suggested React + Plotly stack: it needs
no Node toolchain and no CDN, so `python run.py` is genuinely the only step, and
the charts render identically offline. The code is organised the way a React app
would be (`components/`, `pages/`, `services/`), so porting is mechanical — the
API contract is unchanged.

### Database

SQLite by default; set `DATABASE_URL` to a `postgresql+psycopg://` URL and the
identical schema runs on PostgreSQL. Tables: `users`, `resumes`, `companies`,
`job_roles`, `skills`, `company_requirements`, `resume_analyses`,
`recommendations`, `project_recommendations`, with foreign keys and cascades.
Reference data is mirrored from the JSON datasets on startup (idempotent).

---

## API

Full interactive documentation at `/docs`. Summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status, active NLP backend, dataset counts |
| GET | `/api/catalog` | Companies, roles, levels, weights — everything the picker needs |
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
| POST | `/api/projects/recommend` | Projects for an explicit skill list |
| GET | `/api/roadmap/{analysis_id}` | Roadmap for a stored analysis |
| POST | `/api/chat` | Grounded career assistant |

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"resume_id":1,"company":"amazon","role":"machine-learning-engineer","level":"entry"}'
```

See [docs/API.md](docs/API.md) for the response shape.

---

## Extending it

Adding a company or role means adding a JSON object — no code changes.

```jsonc
// backend/datasets/companies.json
{
  "id": "stripe",
  "name": "Stripe",
  "tagline": "Payments infrastructure at global scale.",
  "values": ["Users First", "Rigour", "Global Optimism"],
  "focus_skills": [
    {"skill": "Go", "boost": 0.25, "promote_to": "required"},
    {"skill": "Security", "boost": 0.2}
  ],
  "keywords": ["reliability", "financial infrastructure", "api design"],
  "hiring_signals": ["Evidence of correctness-critical work"],
  "screen_notes": "…",
  "interview_focus": ["Systems design", "Practical coding"]
}
```

`focus_skills` raise a skill's importance and can promote it to *required*.
Restart (or call `python run.py --seed`) and the new company appears in the
picker, the API and the database. The test suite includes a check that every
skill referenced by any dataset exists in the ontology, so typos fail loudly.

See [docs/DATASETS.md](docs/DATASETS.md) for the full schema of each file.

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

## Configuration

Copy `.env.example` to `.env`. Every value has a working default.

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address |
| `DEBUG` | `false` (`true` via `run.py`) | Auto-reload, verbose errors, no-cache static assets |
| `DATABASE_URL` | SQLite file | Set a PostgreSQL URL for production |
| `MAX_UPLOAD_MB` | `10` | Upload size limit |
| `STORE_UPLOADED_FILES` | `false` | Keep the original file, not just extracted text |
| `ENABLE_SPACY` / `SPACY_MODEL` | `true` / `en_core_web_sm` | NLP backend |
| `ANTHROPIC_API_KEY` | *(empty)* | Enables generative rewrites |
| `CORS_ORIGINS` | `*` | Restrict to your frontend origin when deployed |
| `WEB_CONCURRENCY` | `1` | Each worker loads its own ~350 MB of models |
| `LLM_MODEL` | `claude-sonnet-5` | Model for the optional LLM path |

---

## Troubleshooting

**"Could not reach the API"** — the backend is not running. Start it with
`python run.py` and reload the page.

**Frontend changes do nothing** — bump the `?v=` query on the asset links in
`frontend/index.html`; browsers cache ES modules aggressively. In `DEBUG` mode
the server also sends `Cache-Control: no-store` for non-API routes.

**"No text could be extracted from this PDF"** — it is a scan or an image.
Export a text-based PDF; ATS parsers cannot read it either, which is itself the
finding.

**Low keyword score** — expected on a first run: it measures how much of the
target's own vocabulary appears in your resume. Use their phrasing only where it
describes work you genuinely did.

**spaCy model missing** — `python -m spacy download en_core_web_sm`. Without it
the app still runs on the regex pipeline; `/api/health` reports which is active.

---

## Testing

```bash
pip install -r backend/requirements-dev.txt   # pytest + httpx, once
pytest backend/tests -q                    # full suite
pytest backend/tests -q -k Honesty         # the fabrication guarantees
python backend/tests/manual/calibrate.py   # score scale across targets
python backend/tests/manual/smoke.py       # full pipeline, printed
python backend/tests/manual/api_check.py   # HTTP checks against a running server
python backend/tests/manual/edge_cases.py  # adversarial resume sweep
```

The suite covers dataset integrity, parsing (including real PDF/DOCX),
ambiguous-skill matching, credit rules, company specificity, scoring bounds and
reconstruction, section scores, ATS behaviour, the honesty guarantees, JD
parsing and every API error path.

`python backend/tests/manual/edge_cases.py` runs an adversarial sweep - resumes
with no headings, headings with no content, keyword stuffing, unicode, four date
formats, 2000-word documents and markup injection attempts. Every case must
produce a usable analysis or a clear typed error, never a stack trace.
