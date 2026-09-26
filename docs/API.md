# API reference

Interactive documentation (with request/response schemas and a try-it console)
is served at **`/docs`**; the OpenAPI document is at `/openapi.json`. This page
covers the analysis payload, which is intentionally an open JSON object.

Base URL: `http://127.0.0.1:8000`

---

## Catalog

### `GET /api/catalog`
Everything the target picker needs in one call: companies, roles, levels,
skill/project counts and the default scoring weights.

### `GET /api/catalog/requirements/{company}/{role}?level=entry`
The composed requirement profile for a target — required, preferred and optional
skills with importance, keywords, responsibilities, company values, hiring
signals and screening notes. `404` for an unknown company or role.

### `GET /api/catalog/scoring`
The scoring formula, default and per-level weights, the credit rules and the
band thresholds. This is the contract behind every number in the dashboard.

### `GET /api/catalog/skills?category=cloud&search=aws`
The skill ontology, filterable by category and by name/alias search.

---

## Resume

### `POST /api/resume/upload`
`multipart/form-data` with a `file` field. PDF, DOCX or TXT, up to 10 MB.

```json
{
  "resume_id": 1,
  "file_name": "resume.pdf",
  "contact": {"name": "…", "email": "…", "phone": "…", "linkedin": "…", "github": "…"},
  "sections_detected": ["skills", "experience", "projects", "education"],
  "skills_detected": ["Python", "SQL", "…"],
  "skill_profile": {"total": 27, "applied": 14, "by_category": {"…": 5}},
  "metadata": {"words": 312, "pages": 1, "extractor": "pymupdf", "warnings": []},
  "parsed": { "…full structured resume…" }
}
```

Errors: `415` unsupported type, `413` too large, `400` empty,
`422` no extractable text (scanned PDF).

### `POST /api/resume/parse-text`
Form field `resume_text`. Same response shape.

### `GET /api/resume/{id}` · `DELETE /api/resume/{id}`

---

## Analysis

### `POST /api/analyze`

```json
{
  "resume_id": 1,
  "company": "amazon",
  "role": "machine-learning-engineer",
  "level": "entry",
  "persist": true
}
```

`resume_text` may be sent instead of `resume_id`. Errors: `404` unknown company,
role or resume; `400` neither resume field supplied; `422` validation.

The response is the full analysis:

```jsonc
{
  "analysis_id": 12,
  "generated_at": "2026-09-01T12:34:56Z",

  "target": {
    "company": {"id": "amazon", "name": "Amazon"},
    "role": {"id": "machine-learning-engineer", "title": "Machine Learning Engineer"},
    "level": {"id": "entry", "title": "Entry Level (0-2 years)"},
    "curated": true,
    "required_skills": [{"skill": "AWS", "importance": 0.95, "priority": "high", "…": "…"}],
    "preferred_skills": [], "optional_skills": [],
    "keywords": [], "responsibilities": [], "values": [],
    "hiring_signals": [], "screen_notes": "…", "interview_focus": [],
    "weights": {"skills": 0.35, "…": 0.2}
  },

  "resume_overview": {
    "contact": {}, "metadata": {},
    "skill_profile": {"total": 27, "applied": 14, "emerging": []},
    "skills_by_category": {"ml": [{"name": "Python", "confidence": 1.0,
                                   "applied": true, "evidence": [{"section": "experience",
                                   "snippet": "…", "matched": "Python"}]}]},
    "education": [], "experience": [], "projects": [], "certifications": []
  },

  "scoring": {
    "overall_score": 40.4,
    "band": "Developing Match",
    "band_message": "…",
    "narrative": "Your strongest area is …",
    "methodology": {"formula": "overall = Σ (component_score × weight) ÷ Σ weights",
                    "weights": {}, "note": "…"},
    "breakdown": [
      {"key": "skills", "label": "Skills Match", "score": 36.4,
       "weight": 0.35, "weight_percent": 35.0, "contribution": 12.7,
       "method": "Importance-weighted coverage …",
       "detail": "6 of 13 required skills fully evidenced …",
       "evidence": {"required_total": 13, "required_matched": 6, "…": 0}}
    ]
  },

  "ats": {
    "score": 73.7, "band": "Mostly Compatible", "summary": "…",
    "family_scores": {"parsability": {"score": 100.0, "label": "Parsability"}},
    "checks": [{"id": "quantified", "family": "content", "label": "Quantified results",
                "status": "warn", "points": 4.8, "max_points": 12.0,
                "message": "…", "suggestion": "…"}],
    "critical_issues": [], "warnings": [], "formatting_warnings": []
  },

  "section_scores": {
    "overall": 73.4,
    "weakest_section": "summary",
    "summary": "Your professional summary section is the weakest at 45/100 - specific, not generic.",
    "sections": [
      {"key": "summary", "label": "Professional Summary", "score": 45.0,
       "present": true, "verdict": "weak", "weakest": "Specific, not generic",
       "checks": [{"label": "Specific, not generic", "status": "fail",
                   "points": 0.0, "max_points": 25,
                   "detail": "Contains generic filler: passionate."}]}
    ],
    "note": "Section scores show which part of the document to edit …"
  },

  "skill_gap": {
    "matched": [], "partially_matched": [],
    "missing_high_priority": [{"skill": "AWS", "importance": 0.855, "priority": "high",
                               "status": "missing", "credit": 0.0, "learn_weeks": 8,
                               "reason": "No evidence of AWS found anywhere in the resume",
                               "via": "", "evidence": ""}],
    "missing_medium_priority": [], "missing_low_priority": [],
    "optional": [], "emerging": [], "additional_skills": [],
    "counts": {"matched": 7, "partial": 6, "missing_high": 2, "…": 0}
  },

  "keyword_analysis": {"coverage": 0.14, "present": [], "partial": [], "missing": [],
                       "total": 22, "note": "…"},
  "experience_analysis": {"score": 49.4, "detected_years": 0.8, "expected_years": 1.0,
                          "gap_years": 0.2, "relevance": 0.11, "roles_found": [],
                          "quantified_bullets": 2, "total_bullets": 7, "detail": "…"},

  "ai_suggestions": {
    "engine": {"mode": "rule-based", "honesty_rules": []},
    "sections": {
      "experience": [{"section": "experience", "kind": "rewrite",
                      "original": "Worked on a customer churn prediction model …",
                      "suggested": "Trained a customer churn prediction model … [add a measurable result …]",
                      "rationale": "…", "tags": ["action-verb", "quantify"],
                      "label": "SUGGESTED REWRITE — verify …",
                      "requires_verification": true}]
    },
    "ethics": {"principle": "Optimise presentation of genuine experience …"},
    "priority_actions": [{"priority": "high", "type": "presentation",
                          "action": "…", "detail": "…", "effort": "under an hour"}]
  },

  "project_recommendations": [
    {"id": "e2e-ml-aws", "title": "Deploy an End-to-End Machine Learning Model on AWS",
     "difficulty": "Intermediate", "duration_weeks": 4, "estimated_duration": "4 weeks",
     "skills_gained": [], "skills_closed": ["AWS", "Docker", "MLOps"],
     "learning_objectives": [], "deliverables": [], "verification": "…",
     "resume_bullet_template": "Deployed a <model type> model …",
     "fit_score": 89.3, "gap_coverage": 31.2, "priority": "high", "rationale": "…"}
  ],

  "learning_roadmap": {
    "target": "Amazon · Machine Learning Engineer · Entry Level (0-2 years)",
    "current_state": {"matched_skills": [], "matched_count": 7, "gap_count": 16},
    "phases": [{"phase": 1, "title": "Surface what you already have",
                "duration_weeks": 1, "type": "resume", "why": "…",
                "actions": [{"action": "…", "detail": "…", "skill": "Docker"}],
                "skills": []}],
    "total_duration_weeks": 33, "estimated_completion": "about 8 months",
    "projection": {"current_skills_score": 36.4, "after_presentation_fixes": 44.0,
                   "after_closing_high_priority": 53.1, "note": "…"},
    "principle": "…"
  },

  "skill_priority_plan": [{"order": 1, "skill": "AWS", "priority": "high",
                           "estimated_weeks": 8, "cumulative_weeks": 8, "why": "…"}],

  "charts": {
    "gauge": {"value": 40.4, "band": "…", "thresholds": [40, 55, 70, 85]},
    "skill_pie": {"labels": [], "values": [], "colors": []},
    "radar": {"axes": [{"axis": "Machine Learning & AI", "candidate": 52.0,
                        "target": 100.0, "skills_total": 8, "skills_matched": 4}]},
    "missing_bar": {"labels": [], "values": [], "priorities": [], "statuses": []},
    "component_bars": [], "ats_families": [],
    "section_scores": [{"key": "summary", "label": "Professional Summary",
                        "score": 45.0, "verdict": "weak"}],
    "readiness": {"current": 40.4, "after_presentation": 43.0, "after_learning": 46.2}
  },

  "insights": [{"type": "gap", "title": "2 blocking gap(s) for Amazon", "body": "…"}],
  "pipeline": {"nlp_backend": {"backend": "spacy", "detail": "spaCy 3.8.16 (en_core_web_sm)"},
               "similarity_method": "sklearn-tfidf", "ai_engine": "rule-based", "stages": []}
}
```

### `fit_assessment` (in every analysis response)

Answers "should I apply?", which is a different question from "what is my
score?". Any single check can veto the verdict:

```json
"fit_assessment": {
  "verdict": "Not a fit",            // Strong fit | Good fit | Partial fit | Not a fit
  "is_fit": false,                   // true for Strong and Good
  "confidence": 88.0,
  "headline": "Not worth applying to this Machine Learning Engineer role yet …",
  "required_coverage": 35.0,
  "knockouts": ["experience"],
  "checks": [
    {"key": "required_coverage", "label": "Required skills", "status": "fail",
     "detail": "35% of 9 required skills evidenced (2 fully, 2 partially).",
     "knockout": true}
  ],
  "blocking_skills": ["AWS", "Kubernetes"],
  "strengths": ["Python", "Project Relevance 85/100"],
  "next_step": "Close AWS, Kubernetes before applying. …"
}
```

| Check | Knockout when |
|---|---|
| `required_coverage` | below 40% of required skills (partials count at their credit) |
| `experience` | **only** when the posting states a number and the gap is ≥ 2 years |
| `degree` | the posting requires a Master's or PhD and the resume shows neither |
| `blocking_gaps`, `overall_score` | never — they inform the verdict, they do not veto it |

A catalog target (company + role + level) carries no employer-stated years, so
its experience expectation is guidance and can only warn.

### `POST /api/analyze/job-description`

```json
{
  "resume_id": 1,
  "job_description": "…the full posting…",
  "level": "mid",
  "company": "amazon",
  "role": "machine-learning-engineer"
}
```

`company` and `role` are optional: supply them to **fuse** the posting with the
curated company profile (the posting supplies the hard requirements, the profile
adds cultural and keyword context). The response is the standard analysis plus:

```json
"job_description_analysis": {
  "domain": {
    "is_tech": true, "confidence": 100.0, "tech_skill_count": 15,
    "tech_signals": ["engineer", "machine learning"], "non_tech_signals": []
  },
  "degree_required": {
    "level": "master", "level_label": "Master's degree",
    "field": "Computer Science", "stated": true,
    "equivalent_allowed": false, "evidence": "Master's degree in Computer Science…"
  },
  "detected_company": "Amazon",
  "detected_role": "Machine Learning Engineer",
  "detected_level": "Mid Level (2-5 years)",
  "years_required": 3.0,
  "required_skills": [], "preferred_skills": [],
  "responsibilities": [], "keywords": [],
  "sections_found": ["required", "preferred", "responsibilities"],
  "fused_with_company_profile": true
}
```

`422` if the posting is too short or contains no recognisable skills.

**Non-technical postings are refused,** not scored badly. The platform's
ontology, company profiles and project library are all technical, so a sales or
nursing posting would produce a confident number that measured nothing. Those
return `422` with a distinct code:

```json
{
  "detail": "This doesn't look like a tech job description. …",
  "code": "non_tech_jd",
  "domain": {"is_tech": false, "tech_skill_count": 0,
             "non_tech_signals": ["marketing", "sales"]}
}
```

A posting is refused only when it names fewer than 3 technical skills **and**
uses more non-technical than technical vocabulary — so a genuine ML posting that
mentions "customer support" still passes.

### `GET /api/analysis/{id}` · `GET /api/analyses?resume_id=&limit=`
### `GET /api/roadmap/{analysis_id}`

---

## Resume builder

### `POST /api/resume/build`

Generates an improved resume from a stored analysis and re-scores its own output
against the same requirement.

```json
{
  "analysis_id": 12,
  "mode": "confirmed",
  "confirmed_skills": ["AWS"],
  "learning_skills": ["MLOps"],
  "details": {"phone": "+91 98765 43210", "portfolio": "yoursite.dev"}
}
```

| Field | Meaning |
|---|---|
| `mode` | `confirmed` (default) adds only `confirmed_skills`. `auto_add` adds every missing required and preferred skill without asking. |
| `confirmed_skills` | Gaps the user states they genuinely have. |
| `learning_skills` | Gaps in progress — rendered on a separate "Currently learning" line, never in the skills list. |
| `details` | Contact fields to fill in or override. |
| `projects_built` | Recommended-project ids the user confirms they built. The bullet is inserted with its `<…>` blanks intact. |
| `projects_in_progress` | Project ids part-way through; listed on a separate, labelled `In progress:` line. |

Project ids come from `recommended_projects` in a previous build response. An
unknown id, or the same id in both lists, returns `422`.

Both `confirmed_skills` and `learning_skills` must name skills that appear in
that analysis's gap lists, and a skill cannot be in both — either returns `422`.

```json
{
  "resume": { "contact": {}, "summary": [], "skills": [], "experience": [] },
  "text": "ANANYA SHARMA
…",
  "changes": [{"section": "Skills", "action": "…", "detail": "…"}],
  "missing_details": [{"field": "portfolio", "label": "Portfolio or personal site",
                       "essential": false}],
  "placeholder_count": 14,
  "unfilled_blanks": 4,
  "projects_added": {"built": ["Deploy an End-to-End ML Model on AWS"],
                     "in_progress": ["Reproducible MLOps Pipeline"]},
  "added_project_warning": "You said you have built this…",
  "recommended_projects": [{"id": "e2e-ml-aws", "title": "…",
                            "resume_bullet_template": "Deployed a <model type> model…"}],
  "mode": "confirmed",
  "skills_added": {"confirmed": ["AWS"], "auto_added": [], "learning": ["MLOps"]},
  "auto_added_skills": [],
  "auto_add_warning": "",
  "score": {"before": 40.4, "after": 44.8,
            "fit_before": "Partial fit", "fit_after": "Partial fit",
            "band_before": "Developing Match", "band_after": "Developing Match"}
}
```

`score.after` is **measured**, not estimated: the generated text is re-parsed and
run through the identical matching and scoring pipeline.

In `auto_add` mode the added skills are returned in `auto_added_skills` with
`auto_add_warning` set, and the change log records it. See the honesty contract
in the README — this mode is the one explicit opt-out.

### `POST /api/resume/export`

Renders the (usually user-edited) text as a file download.

```json
{"text": "ANANYA SHARMA
…", "format": "docx",
 "strip_placeholders": true, "file_name": "Ananya Sharma"}
```

| Field | Meaning |
|---|---|
| `format` | `docx`, `pdf` or `txt` |
| `strip_placeholders` | Default `true` — removes the optional `[ … ]` prompts |

**`< … >` blanks are never stripped.** They are content the candidate must
supply, and deleting them would turn a template into a claim, so the export
returns `422` listing what is still unfilled. Send `strip_placeholders: false`
to download the document with every marker intact.
| `file_name` | Sanitised; the extension is added automatically |

Returns the file with the matching `Content-Type` and a
`Content-Disposition: attachment` header (exposed to cross-origin callers).
DOCX and PDF are deliberately ATS-plain: single column, black text, no tables,
images or colour.

## Projects

### `POST /api/projects/recommend`

```json
{"missing_skills": ["AWS", "Docker", "MLOps"],
 "role": "machine-learning-engineer", "company": "amazon", "limit": 6}
```

Returns ranked projects plus `unrecognised_skills` for anything outside the
ontology. `422` if none of the supplied skills are recognised.

---

## Assistant

### `POST /api/chat`

```json
{"question": "What should I learn first?", "analysis_id": 12}
```

Send `analysis` inline instead of `analysis_id` for an unsaved analysis.

```json
{"answer": "Learn these in this order …", "intent": "learn_first",
 "suggested_questions": ["…"], "grounded": true, "engine": "rule-based"}
```

Requests to fabricate credentials are detected (`intent: "fabricate"`) and
declined, with the honest route offered instead.

### `GET /api/chat/starters`

---

## Errors

All errors return a JSON body:

```json
{"detail": "Unknown company 'foo'. See GET /api/catalog/companies.",
 "code": "error", "hint": null}
```

Validation failures add a `problems` array with `field` and `message` per issue.

| Status | Meaning |
|---|---|
| 400 | Missing required input (e.g. neither `resume_id` nor `resume_text`) |
| 404 | Unknown company, role, resume or analysis |
| 413 | Upload exceeds `MAX_UPLOAD_MB` |
| 415 | Unsupported file type |
| 422 | Validation failed, the file contained no extractable text, or a claimed skill is not a gap |
| 422 `code: non_tech_jd` | The pasted posting is not a technical role |
| 500 | Unexpected error (`hint` carries the detail when `DEBUG=true`) |

Every response carries an `X-Process-Time-Ms` header.
