"""Similarity model.

Two complementary measures are exposed:

``tfidf_cosine``
    Classic bag-of-words similarity between the resume and the target
    requirement text, using scikit-learn's TF-IDF vectoriser with 1-2 grams.

``semantic_similarity``
    A softer measure that also credits *related* concepts: it combines TF-IDF
    cosine with lemma-overlap (Jaccard) and a skill-graph expansion, so a
    resume that says "PyTorch" gets partial credit against a requirement that
    says "Deep Learning".

If scikit-learn is unavailable the module falls back to a NumPy implementation
of the same maths, so the API contract never changes.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from ml.nlp_pipeline import STOPWORDS, get_pipeline

try:  # pragma: no cover - exercised implicitly by the fallback path
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover
    SKLEARN_AVAILABLE = False


@dataclass
class SimilarityResult:
    tfidf_cosine: float
    lemma_overlap: float
    semantic: float
    shared_terms: list[str]
    method: str

    def to_dict(self) -> dict:
        return {
            "tfidf_cosine": round(self.tfidf_cosine, 4),
            "lemma_overlap": round(self.lemma_overlap, 4),
            "semantic": round(self.semantic, 4),
            "shared_terms": self.shared_terms[:25],
            "method": self.method,
        }


class SimilarityModel:
    """TF-IDF + cosine similarity with a dependency-free fallback."""

    def __init__(self) -> None:
        self.nlp = get_pipeline()
        self.method = "sklearn-tfidf" if SKLEARN_AVAILABLE else "numpy-tfidf"

    # -- core measures -----------------------------------------------------

    def tfidf_cosine(self, text_a: str, text_b: str) -> float:
        a, b = (text_a or "").strip(), (text_b or "").strip()
        if not a or not b:
            return 0.0
        if SKLEARN_AVAILABLE:
            try:
                vectoriser = TfidfVectorizer(
                    stop_words="english",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    min_df=1,
                    token_pattern=r"(?u)\b[A-Za-z][A-Za-z0-9+#./_-]+\b",
                )
                matrix = vectoriser.fit_transform([a, b])
                return float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
            except ValueError:
                # Happens when both documents are entirely stopwords.
                return 0.0
        return self._fallback_cosine(a, b)

    def _fallback_cosine(self, a: str, b: str) -> float:
        """Manual TF-IDF cosine over a two-document corpus."""
        docs = [self._terms(a), self._terms(b)]
        vocab = set(docs[0]) | set(docs[1])
        if not vocab:
            return 0.0
        vectors = []
        for terms in docs:
            counts = Counter(terms)
            total = sum(counts.values()) or 1
            vector = {}
            for term in vocab:
                tf = counts.get(term, 0) / total
                df = sum(1 for d in docs if term in d)
                idf = math.log((1 + 2) / (1 + df)) + 1.0
                vector[term] = tf * idf
            vectors.append(vector)
        dot = sum(vectors[0][t] * vectors[1][t] for t in vocab)
        na = math.sqrt(sum(v * v for v in vectors[0].values()))
        nb = math.sqrt(sum(v * v for v in vectors[1].values()))
        return float(dot / (na * nb)) if na and nb else 0.0

    def _terms(self, text: str) -> list[str]:
        doc = self.nlp.analyse(text)
        unigrams = doc.content_lemmas
        bigrams = [
            f"{unigrams[i]} {unigrams[i+1]}" for i in range(len(unigrams) - 1)
        ]
        return unigrams + bigrams

    def lemma_overlap(self, text_a: str, text_b: str) -> tuple[float, list[str]]:
        """Jaccard overlap of content lemmas, plus the shared terms."""
        set_a = set(self.nlp.analyse(text_a).content_lemmas)
        set_b = set(self.nlp.analyse(text_b).content_lemmas)
        if not set_a or not set_b:
            return 0.0, []
        shared = set_a & set_b
        union = set_a | set_b
        ranked = sorted(shared, key=lambda t: (-len(t), t))
        return len(shared) / len(union), ranked

    # -- composite ---------------------------------------------------------

    def compare(
        self,
        resume_text: str,
        requirement_text: str,
        expanded_resume_terms: Iterable[str] = (),
    ) -> SimilarityResult:
        """Full comparison used by the scoring engine.

        ``expanded_resume_terms`` lets the caller inject skill-graph expansions
        (related skills of everything detected in the resume) so conceptually
        adjacent experience earns partial semantic credit.
        """
        expanded = " ".join(expanded_resume_terms)
        cosine = self.tfidf_cosine(resume_text, requirement_text)
        overlap, shared = self.lemma_overlap(resume_text, requirement_text)
        expanded_cosine = (
            self.tfidf_cosine(f"{resume_text} {expanded}", requirement_text)
            if expanded
            else cosine
        )
        # Weighted blend: the expanded cosine dominates, lexical overlap keeps
        # the score honest when the vectoriser latches onto boilerplate.
        semantic = 0.6 * expanded_cosine + 0.25 * cosine + 0.15 * overlap
        return SimilarityResult(
            tfidf_cosine=cosine,
            lemma_overlap=overlap,
            semantic=min(1.0, semantic),
            shared_terms=[t for t in shared if t not in STOPWORDS],
            method=self.method,
        )

    def keyword_coverage(
        self, resume_text: str, keywords: list[str]
    ) -> tuple[float, list[str], list[str], list[str]]:
        """Coverage of the target's keywords, with partial credit.

        A keyword is *present* when the whole phrase appears or every content
        word of the phrase appears somewhere in the resume; it is *partial*
        when at least half of its content words appear. Partial matches count
        as half a keyword, so a resume that talks about "deployment" but not
        "model deployment" is not scored as if it said nothing at all.

        Returns ``(coverage, present, partial, missing)``.
        """
        if not keywords:
            return 0.0, [], [], []
        haystack = " " + (resume_text or "").lower() + " "
        lemma_set = set(self.nlp.analyse(resume_text).content_lemmas)
        # Lemmatise every content word across all keywords in a single pass.
        lemma_map = self.nlp.lemmatise_many(
            word for keyword in keywords for word in keyword.lower().split()
            if word not in STOPWORDS
        )
        present: list[str] = []
        partial: list[str] = []
        missing: list[str] = []
        for keyword in keywords:
            phrase = keyword.lower().strip()
            if not phrase:
                continue
            if phrase in haystack:
                present.append(keyword)
                continue
            words = [w for w in phrase.split() if w not in STOPWORDS]
            lemmas = {lemma_map.get(w, w) for w in words}
            if not lemmas:
                missing.append(keyword)
                continue
            hit_ratio = len(lemmas & lemma_set) / len(lemmas)
            if hit_ratio >= 1.0:
                present.append(keyword)
            elif hit_ratio >= 0.5:
                partial.append(keyword)
            else:
                missing.append(keyword)
        total = len(present) + len(partial) + len(missing)
        coverage = (len(present) + 0.5 * len(partial)) / max(1, total)
        return coverage, present, partial, missing

_MODEL: SimilarityModel | None = None


def get_similarity_model() -> SimilarityModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = SimilarityModel()
    return _MODEL
