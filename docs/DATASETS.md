# Datasets

The JSON files in `backend/datasets/` are the source of truth. Adding a company,
role, skill or project requires no code change — the loader indexes whatever is
there, and the database is re-seeded from it on startup.

| File | Contents |
|---|---|
| `skills.json` | The canonical skill ontology (144 skills, 11 categories) |
| `roles.json` | 10 role baselines with required/preferred/optional skills |
| `companies.json` | 9 company profiles that modify role baselines |
| `company_role_overrides.json` | 12 curated company × role refinements |
| `experience_levels.json` | 4 levels with scoring weights and expectations |
| `projects.json` | 22 projects mapped to the skills they teach |

## skills.json

```jsonc
{
  "name": "Amazon SageMaker",     // canonical name used everywhere
  "category": "cloud",            // key from the categories map
  "aliases": ["sagemaker"],       // surface forms that count as evidence
  "learn_weeks": 5,               // drives roadmap time estimates
  "related": ["AWS", "MLOps"],    // skill graph: partial credit + expansion
  "emerging": false               // flags differentiator skills
}
```

Aliases are matched case-insensitively with word boundaries, tolerating spacing
and hyphenation (`scikit learn`, `scikit-learn`). Names that collide with
ordinary English (`C`, `R`, `Go`, `C#`, `.NET`) are handled by the
case-sensitive `AMBIGUOUS` patterns in `services/skill_extractor.py` — add an
entry there if you introduce another short name.

`related` is used two ways: to award partial credit when an adjacent skill is
present, and to expand the resume vector for semantic similarity.

## roles.json

```jsonc
{
  "id": "machine-learning-engineer",
  "title": "Machine Learning Engineer",
  "family": "ai",
  "summary": "…",
  "radar_axes": ["ml", "cloud", "devops", "data", "language"],
  "required_skills":  [{"skill": "Python", "importance": 1.0}],
  "preferred_skills": [{"skill": "MLOps",  "importance": 0.8}],
  "optional_skills":  [{"skill": "Terraform", "importance": 0.35}],
  "keywords": ["model deployment", "production ml"],
  "responsibilities": ["…"],
  "soft_skills": ["Ownership", "Collaboration"]
}
```

`importance` (0–1) drives both the weighted score and the priority band.
`radar_axes` are the skill categories plotted on the radar chart.

## companies.json

A company never replaces a role — it modifies it.

```jsonc
{
  "id": "amazon",
  "name": "Amazon",
  "tagline": "Scale, ownership and measurable customer impact.",
  "values": ["Customer Obsession", "Ownership"],
  "focus_skills": [
    {"skill": "AWS", "boost": 0.3, "promote_to": "required"},
    {"skill": "System Design", "boost": 0.15}
  ],
  "keywords": ["customer obsession", "scalable systems"],
  "hiring_signals": ["Bullets that quantify impact"],
  "screen_notes": "…",
  "interview_focus": ["Leadership Principles", "System design"]
}
```

`boost` is added to the skill importance (capped at 1.0). `promote_to` can raise
a preferred or optional skill to `required`. A focus skill the role does not
list at all is added as preferred with `0.5 + boost` as its importance.

## company_role_overrides.json

Optional hand-curated refinements for combinations worth getting exactly right.
Any combination *without* an entry still works — it composes from the role and
company files.

```jsonc
{
  "company": "amazon",
  "role": "machine-learning-engineer",
  "extra_required":  [{"skill": "Amazon SageMaker", "importance": 0.85}],
  "extra_preferred": [{"skill": "Apache Spark", "importance": 0.65}],
  "keywords": ["sagemaker pipelines", "cost per inference"],
  "responsibilities": ["…"],
  "notes": "Surfaced to the user as 'how they screen'."
}
```

## experience_levels.json

```jsonc
{
  "id": "entry",
  "title": "Entry Level (0-2 years)",
  "expected_years": 1,
  "importance_scale": 0.9,       // multiplies every requirement importance
  "weights": {"skills": 0.35, "keywords": 0.2, "experience": 0.1,
              "projects": 0.2, "education": 0.08, "semantic": 0.07},
  "expectations": ["…"]
}
```

## projects.json

```jsonc
{
  "id": "e2e-ml-aws",
  "title": "Deploy an End-to-End Machine Learning Model on AWS",
  "description": "…",
  "difficulty": "Intermediate",          // Beginner | Intermediate | Advanced
  "duration_weeks": 4,
  "skills_taught": ["AWS", "Docker", "Model Deployment"],
  "prerequisites": ["Python", "Machine Learning"],
  "objectives": ["…"],
  "deliverables": ["…"],
  "roles": ["machine-learning-engineer"],   // role affinity
  "companies": ["amazon", "netflix"],       // company affinity
  "resume_bullet_template": "Deployed a <model type> model … at <latency> ms p95.",
  "verification": "Keep the endpoint reachable — interviewers ask to see it."
}
```

`skills_taught` must use canonical ontology names — that is how the recommender
maps projects to gaps. `resume_bullet_template` is a fill-in-the-blank scaffold,
always presented as something to use *after* finishing the project.

## Validation

`pytest backend/tests -q -k referenced_skill` asserts that every skill named in
any dataset exists in `skills.json`, so a typo fails loudly instead of silently
becoming an undetectable requirement.
