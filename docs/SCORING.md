# Scoring methodology

Nothing in this application returns a hardcoded number. Every score is computed
from measurable evidence and returned together with the method and the inputs
that produced it. `GET /api/catalog/scoring` serves this same information at
runtime.

## The formula

```
overall = Σ (component_score × weight) ÷ Σ weights
```

Six components, each scored 0–100 independently:

| Key | Component | Measured by |
|---|---|---|
| `skills` | Skills match | Importance-weighted coverage of the requirement set |
| `keywords` | Keyword alignment | Share of target keywords evidenced in the text |
| `experience` | Experience relevance | Years detected, cosine relevance, quantified bullets |
| `projects` | Project relevance | Weighted skill overlap, depth, measured outcomes |
| `education` | Education & certifications | Degree relevance, level, certifications |
| `semantic` | Semantic similarity | TF-IDF cosine + skill-graph expansion |

## Weights by experience level

Weights are a property of the level, not a constant, so a student is not scored
on the same experience axis as a senior hire.

| Level | skills | keywords | experience | projects | education | semantic |
|---|---|---|---|---|---|---|
| Internship | 35% | 20% | 5% | 25% | 10% | 5% |
| Entry (0–2y) | 35% | 20% | 10% | 20% | 8% | 7% |
| Mid (2–5y) | 35% | 20% | 15% | 15% | 5% | 10% |
| Senior (5y+) | 32% | 18% | 25% | 10% | 3% | 12% |

Weights are normalised, so a partial or custom set still sums to 1.

## Credit rules

The skills component is not a count — it is importance-weighted, and *where* the
evidence appears changes the credit:

| Evidence | Credit | Bucket |
|---|---|---|
| Applied in an experience or project bullet | 1.00 | matched |
| Mentioned outside the skills section | 0.80 | matched |
| Listed in the skills section only | 0.80 | partial |
| An applied, directly related skill is present | 0.35 | partial |
| No evidence | 0.00 | missing |

```
skills_score = Σ (importance × credit) ÷ Σ importance × 100
```

This is why the analysis so often reports a "free" gain: moving a skill from the
skills list into a real bullet raises its credit from partial to fully matched
without learning anything new.

## Importance and priority

Each requirement carries an importance of 0–1 from the role baseline, adjusted
by the company profile and rescaled by the level:

| Priority | Rule | Meaning |
|---|---|---|
| high | importance ≥ 0.85 | Essential — screens fail here |
| medium | 0.65 ≤ importance < 0.85 | Frequently requested |
| low | importance < 0.65 | Differentiator |

## Component details

**Keywords.** A keyword counts fully when the phrase (or every content word of
it) appears, and half when at least half of its content words appear. Coverage
is `(full + 0.5 × partial) ÷ total`.

**Experience.** `0.5 × duration + 0.3 × relevance + 0.2 × quantified_ratio`,
where duration compares detected years against the level expectation, relevance
is the TF-IDF cosine between the experience section and the requirement text
(rescaled by 0.4), and quantified_ratio is the share of bullets containing a
real measurement.

**Projects.** `0.6 × min(1, weighted_overlap × 3) + 0.25 × depth + 0.15 ×
quantified`, where weighted_overlap is the share of the total requirement
importance covered by skills appearing in the projects section.

**Education.** 55 base for a detected entry, +18 for a relevant field, +12 for a
postgraduate degree, +5 for a stated score, +5 per certification (max +15).

**Semantic.** `0.6 × expanded_cosine + 0.25 × cosine + 0.15 × lemma_overlap`,
rescaled by 0.35 because resume/JD pairs rarely exceed that cosine. The expanded
vector adds the related skills of everything detected, so a resume saying
"PyTorch" earns partial credit against a requirement saying "Deep Learning".

## Bands

| Score | Band |
|---|---|
| 85–100 | Excellent Match |
| 70–84 | Strong Match |
| 55–69 | Moderate Match |
| 40–54 | Developing Match |
| 0–39 | Early Stage |

## Calibration

`python backend/tests/manual/calibrate.py` prints the scale across the sample
resumes and several targets. Representative output:

```
sample_resume   amazon     machine-learning-engineer  entry   40.4  Developing Match
sample_resume   google     data-scientist             entry   43.4  Developing Match
sample_resume   microsoft  software-engineer          entry   35.7  Early Stage
strong_resume   amazon     machine-learning-engineer  mid     79.3  Strong Match
strong_resume   nvidia     machine-learning-engineer  mid     72.6  Strong Match
strong_resume   netflix    data-engineer              mid     56.7  Moderate Match
```

The same strong ML resume scores 79 at Amazon, 73 at NVIDIA (missing CUDA and
C++) and 57 against Netflix data engineering — the target, not just the resume,
moves the number.

## Section scores

A second, independent view of the same evidence: the match score is organised by
*scoring dimension*, section scores by *document structure*, because that is what
you actually edit. Each section is scored 0-100 from its own checks.

| Section | Checks (points) |
|---|---|
| Professional Summary | present (25), length (20), specific not generic (25), aligned to target (30) |
| Skills | present (20), breadth (15), grouped (15), backed by evidence (25), covers target (25) |
| Work Experience | present (20), dated (15), depth (15), action verbs (20), quantified (20), relevance (10) |
| Projects | present (25), count (10), depth (15), stack named (20), measured (20), linked (10) |
| Education | present (30), degree (20), dated (15), field relevance (20), certifications (15) |

`section_score = Σ check_points ÷ Σ max_points × 100`, and each check returns
pass/warn/fail with the reason. The weakest section is surfaced as a dashboard
insight when it scores under 70.

## ATS score

Separate from the match score and computed independently: 16 checks across four
families, each worth a fixed number of points.

| Family | Points | Checks |
|---|---|---|
| Parsability | 27 | Extractable text, single-column layout, no image text, character set |
| Structure | 38 | Contact block, standard headings, length, dated entries |
| Content | 34 | Bullet structure, action verbs, quantified results, third-person voice |
| Keywords | 36 | Target coverage, required skills present, skill placement, no stuffing |

`ats_score = earned ÷ available × 100`. Every check returns its status, points,
message and a concrete fix.
