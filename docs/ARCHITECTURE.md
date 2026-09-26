# Architecture

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ frontend/           build-free ES modules, hand-built SVG    │
│                     charts, hash router, no CDN              │
└───────────────┬──────────────────────────────────────────────┘
                │ JSON over HTTP
┌───────────────▼──────────────────────────────────────────────┐
│ api/routes/         validation and HTTP concerns only        │
│                     catalog · resume · analysis · chat       │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ services/           all business logic                       │
│   analysis_service  orchestrates the pipeline                │
│   knowledge_base    datasets → composed requirements         │
│   resume_parser     files → structured JSON                  │
│   skill_extractor   ontology matching with evidence          │
│   job_matcher       gap analysis + component scores          │
│   ats_analyzer      deterministic ATS checks                 │
│   section_scorer    per-section scores + their working       │
│   fit_evaluator     apply/don't-apply verdict + knockouts    │
│   resume_builder    generates and re-scores a new resume     │
│   resume_export     DOCX / PDF / TXT rendering               │
│   ai_service        rewrites (rule-based + optional LLM)     │
│   recommendation_engine  projects + roadmap                  │
│   jd_parser         pasted job descriptions                  │
│   chat_service      grounded assistant                       │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ ml/                 nlp_pipeline · similarity_model ·        │
│                     scoring_engine                           │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ db/  SQLAlchemy      datasets/  JSON source of truth         │
│      SQLite / PostgreSQL                                     │
└──────────────────────────────────────────────────────────────┘
```

The API layer contains no analysis logic: every route validates input, calls a
service and returns the result. That keeps the pipeline usable from tests, the
CLI scripts and any future frontend without change.

## The analysis pipeline

`AnalysisService.run()` is the single place the stages are wired together:

1. **Parse** — `resume_parser` extracts text (PyMuPDF → pdfplumber → python-docx)
   and segments it into sections, entries and bullets.
2. **Extract** — `skill_extractor` scans every section against the ontology,
   recording section, snippet and matched surface form for each hit.
3. **Compose** — `knowledge_base.build_requirement()` layers role baseline →
   company profile → curated override → experience-level rescaling.
4. **Match** — `job_matcher` resolves every requirement against the extracted
   skills, applies the credit rules, and computes the six component scores.
5. **Score** — `scoring_engine` produces the weighted overall score, band and
   per-component breakdown with methods and evidence.
6. **Fit** — `fit_evaluator` turns the match and score into an apply /
   don't-apply verdict. Independent checks, any of which can veto: required
   coverage, blocking gaps, experience, degree, overall score. Only an
   employer-stated requirement can produce a knockout, never our own estimate.
7. **ATS** — `ats_analyzer` runs 16 point-weighted checks.
8. **Sections** — `section_scorer` scores each part of the document, giving a
   structural view of the same evidence.
9. **Suggest** — `ai_service` generates section-by-section rewrites under the
   honesty contract.
10. **Recommend** — `recommendation_engine` ranks projects by weighted gap
    coverage and sequences the roadmap.
11. **Chart** — `analysis_service` shapes the chart-ready payloads.

`resume_builder` sits outside this pipeline and *re-enters* it: it generates a
document, re-parses it with `resume_parser`, and runs stages 2, 4, 5 and 6 again
against the same requirement. That is why the before/after score is comparable
rather than estimated, and why `JobRequirement.from_dict()` exists — a pasted
job description has no dataset to recompose from, so the target is rebuilt from
the stored payload.

Every stage is independently testable and takes plain data structures.

## Requirement composition

The key design decision: requirements are **composed, never enumerated**. With 9
companies × 10 roles × 4 levels there are 360 targets; enumerating them would be
unmaintainable and would still break the moment a company was added.

```python
role baseline          # required/preferred/optional with importance 0-1
  + company profile    # focus_skills raise importance, may promote tier
  + curated override   # optional hand-written refinements for key combos
  + experience level   # importance_scale + scoring weight redistribution
  = JobRequirement
```

A company can only *modify* the role spine, so a new company automatically works
with all ten roles, and a new role automatically works with all nine companies.

## Performance

A single analysis re-reads the same text through several stages. Two measures
keep that cheap:

* `NLPPipeline.analyse()` memoises parsed documents (bounded cache), so the
  resume is parsed once per request rather than once per stage.
* `NLPPipeline.lemmatise_many()` batches word lemmatisation through spaCy's
  `pipe`. Lemmatising keyword words one at a time made keyword coverage the
  single most expensive stage; batching removed it.

Together these took a 2,000-word resume from ~5.0s to ~1.6s and a typical resume
to ~0.5s, with byte-identical scores (`calibrate.py` is the regression check).

## NLP backends

`NLPPipeline` exposes one interface with three possible backends, selected at
startup and reported by `/api/health`:

| Backend | When | Provides |
|---|---|---|
| `spacy` | spaCy + model installed | Lemmatisation, NER, noun chunks |
| `spacy-blank` | spaCy without the model | Tokenisation, sentences |
| `regex` | spaCy absent | Suffix-stripping lemmas, regex NER, n-gram phrases |

Downstream code never branches on the backend.

## Persistence

JSON datasets are the source of truth; the database mirrors them for
queryability and stores analyses. `init_db()` is idempotent — it creates tables
and upserts reference data on every startup.

Analyses are stored whole (`payload` JSON) plus extracted columns for listing
and filtering. Recommendations and project recommendations are normalised into
their own tables with cascade deletes.

## Frontend

No build step. `index.html` loads `src/app.js` as an ES module; the app is a
hash router over page modules, each exposing `render(state)` and
`mount(root, ctx)`. State lives in a small observable store with the resume id,
target and analysis id persisted to `sessionStorage`.

Charts are hand-built SVG (`components/charts.js`): a 270° gauge, donut, radar,
bar lists and progress meters, all driven by the same design tokens as the rest
of the UI, with a shared hover-tooltip layer.

The layout is an app shell: `.app` is `height: 100vh; overflow: hidden` and the
`.main` column owns scrolling, so the sidebar and topbar stay fixed without
sticky-positioning artefacts. Below 900px the shell stacks and normal document
scrolling is restored.

All rendered content passes through `esc()`; parsed resume text is never
injected as markup.

### Theming

Light is the default; dark is opt-in. The palette is a single token layer:
`:root` carries the light values and `[data-theme="dark"]` overrides them, so a
theme switch is one attribute on `<html>`. Rules never name a colour directly -
they consume `--text`, `--surface`, `--track`, `--ok-text` and so on, with
`color-mix()` used for the tinted borders.

The SVG charts consume the same tokens (`fill="var(--text)"`,
`stroke="var(--track)"`), and JS-chosen colours go through `token()` in
`ui.js` - `scoreColor()` reads `--score-*`, so the gauge and bars follow the
theme without any per-theme branching in the chart code. An inline script in
`index.html` applies the stored theme before the stylesheets paint, so a
dark-theme user never sees a flash of white.

Contrast is verified rather than assumed. Whether a token pair is readable
depends on what it lands on - a chip tint over a card gradient over the page
wash - and that composite only exists at runtime. `frontend/dev/contrast-audit.js`
walks the live DOM, composites every translucent ancestor, and reports anything
under WCAG AA; both themes currently pass on all eight pages.

**Run it after a reload, not after an in-page theme toggle.** Switching theme
with the toggle leaves `getComputedStyle` returning the previous background for
already-painted elements, so the audit composites new text against the old
surface and reports dozens of false failures. Set the theme, reload, then run. Elements sitting
on a CSS gradient are skipped, since their background cannot be read from
`backgroundColor` and would report as false failures.
