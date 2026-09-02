"""Explainable weighted scoring.

No score in this application is hardcoded or hand-waved. Every component is
computed from measurable evidence, carries its own explanation and the exact
inputs that produced it, and contributes to the overall score through a weight
that the API returns alongside the result.

    overall = sum(component_score * weight) / sum(weights)

Default weights (mid-level target):

    skills 35% | keywords 20% | experience 15% | projects 15% | education 5% | semantic 10%

Experience level shifts these - see ``datasets/experience_levels.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {
    "skills": 0.35,
    "keywords": 0.20,
    "experience": 0.15,
    "projects": 0.15,
    "education": 0.05,
    "semantic": 0.10,
}

COMPONENT_LABELS: dict[str, str] = {
    "skills": "Skills Match",
    "keywords": "Keyword Alignment",
    "experience": "Experience Relevance",
    "projects": "Project Relevance",
    "education": "Education & Certifications",
    "semantic": "Semantic Similarity",
}

COMPONENT_METHODS: dict[str, str] = {
    "skills": "Importance-weighted coverage of required, preferred and optional skills",
    "keywords": "Share of company/role keywords evidenced in the resume text",
    "experience": "Detected years and role-relevant work signals against the level expectation",
    "projects": "Skill overlap and depth signals across the projects section",
    "education": "Degree relevance and certification evidence",
    "semantic": "TF-IDF cosine similarity plus skill-graph expansion between resume and target",
}


@dataclass
class ComponentScore:
    """One scored dimension, with the evidence behind it."""

    key: str
    score: float  # 0-100
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return COMPONENT_LABELS.get(self.key, self.key.title())

    def to_dict(self, weight: float) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score, 1),
            "weight": round(weight, 4),
            "weight_percent": round(weight * 100, 1),
            "contribution": round(self.score * weight, 2),
            "method": COMPONENT_METHODS.get(self.key, ""),
            "detail": self.detail,
            "evidence": self.evidence,
        }


BANDS: list[tuple[int, str, str]] = [
    (85, "Excellent Match", "You clear the bar on paper. Focus on interview preparation."),
    (70, "Strong Match", "You are competitive. Close the remaining high-priority gaps to stand out."),
    (55, "Moderate Match", "Real foundation in place, with specific gaps that are worth closing before applying."),
    (40, "Developing Match", "Core direction is right, but several essential requirements are not yet evidenced."),
    (0, "Early Stage", "Significant preparation needed for this specific target. The roadmap below is the fastest route."),
]


@dataclass
class ScoreReport:
    overall: float
    band: str
    band_message: str
    components: list[ComponentScore]
    weights: dict[str, float]

    def strongest(self) -> ComponentScore:
        return max(self.components, key=lambda c: c.score)

    def weakest(self) -> ComponentScore:
        # The biggest opportunity is the lowest score weighted by how much it
        # matters - fixing a 40 that carries 35% beats fixing a 30 that carries 5%.
        return min(
            self.components,
            key=lambda c: c.score + (1 - self.weights.get(c.key, 0.1)) * 40,
        )

    def narrative(self) -> str:
        best, worst = self.strongest(), self.weakest()
        return (
            f"Your strongest area is {best.label.lower()} at {best.score:.0f}/100. "
            f"The biggest improvement opportunity is {worst.label.lower()} at {worst.score:.0f}/100, "
            f"which carries {self.weights.get(worst.key, 0) * 100:.0f}% of the overall score."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": round(self.overall, 1),
            "band": self.band,
            "band_message": self.band_message,
            "narrative": self.narrative(),
            "methodology": {
                "formula": "overall = Σ (component_score × weight) ÷ Σ weights",
                "weights": {k: round(v, 4) for k, v in self.weights.items()},
                "note": (
                    "Weights are set by the selected experience level so students are not "
                    "penalised on the same experience axis as senior candidates."
                ),
            },
            "breakdown": [
                c.to_dict(self.weights.get(c.key, 0.0)) for c in self.components
            ],
        }


class ScoringEngine:
    """Combines component scores into a single, explainable number."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        merged = dict(DEFAULT_WEIGHTS)
        if weights:
            merged.update({k: float(v) for k, v in weights.items() if k in DEFAULT_WEIGHTS})
        total = sum(merged.values()) or 1.0
        # Normalise so a partial or custom weight set still sums to 1.
        self.weights = {k: v / total for k, v in merged.items()}

    def score(self, components: list[ComponentScore]) -> ScoreReport:
        active = [c for c in components if c.key in self.weights]
        total_weight = sum(self.weights[c.key] for c in active) or 1.0
        overall = sum(c.score * self.weights[c.key] for c in active) / total_weight
        overall = max(0.0, min(100.0, overall))
        band, message = next(
            (name, msg) for threshold, name, msg in BANDS if overall >= threshold
        )
        return ScoreReport(
            overall=overall,
            band=band,
            band_message=message,
            components=active,
            weights={c.key: self.weights[c.key] for c in active},
        )


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
