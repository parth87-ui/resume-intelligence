"""NLP pipeline.

spaCy is used when it is installed *and* a model is available; otherwise the
pipeline degrades to a pure-regex implementation that provides the same public
interface. Every downstream module talks to this class only, so the rest of the
system never has to care which backend is active.

Provided by both backends:
    * sentence segmentation
    * tokenisation + lemmatisation
    * stopword filtering
    * noun-phrase / n-gram keyword extraction
    * named entity recognition
    * action-verb and quantified-metric detection
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from config import settings

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

STOPWORDS: set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "did", "do", "does", "doing", "down", "during",
    "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself", "no",
    "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
    "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "while", "who",
    "whom", "why", "will", "with", "you", "your", "yours", "yourself", "yourselves",
    "etc", "via", "using", "used", "use", "within", "across", "including", "e.g", "i.e",
}

# Strong resume action verbs, used by the ATS and rewrite engines.
ACTION_VERBS: set[str] = {
    "architected", "automated", "built", "created", "delivered", "deployed", "designed",
    "developed", "engineered", "implemented", "improved", "increased", "integrated",
    "launched", "led", "migrated", "optimised", "optimized", "orchestrated", "owned",
    "reduced", "refactored", "scaled", "shipped", "streamlined", "trained", "analysed",
    "analyzed", "benchmarked", "debugged", "diagnosed", "drove", "established",
    "evaluated", "instrumented", "mentored", "modelled", "modeled", "prototyped",
    "researched", "resolved", "spearheaded", "standardised", "standardized", "tested",
    "tuned", "validated", "accelerated", "consolidated", "eliminated", "generated",
}

# Verbs that signal a passive / low-ownership bullet.
WEAK_OPENERS: set[str] = {
    "worked", "helped", "assisted", "participated", "involved", "responsible",
    "handled", "supported", "contributed", "familiar", "exposure", "learned",
    "attended", "tasked", "aided",
}

_METRIC_RE = re.compile(
    r"(\d+(?:\.\d+)?\s?%|\$\s?\d[\d,.]*\s?(?:k|m|b|bn|million|billion)?|"
    r"\b\d[\d,]*\s?(?:x|ms|s\b|sec|seconds|minutes|hours|users|customers|requests|rows|"
    r"records|queries|gb|tb|mb|qps|rps|fps|models|events|images|documents|tickets)\b|"
    r"\b\d+(?:\.\d+)?\s?(?:million|billion|thousand)\b)",
    re.IGNORECASE,
)

_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./_-]*")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")

_IRREGULAR_LEMMAS = {
    "built": "build", "led": "lead", "ran": "run", "wrote": "write", "drove": "drive",
    "taught": "teach", "grew": "grow", "brought": "bring", "began": "begin",
    "chose": "choose", "found": "find", "held": "hold", "kept": "keep", "made": "make",
    "met": "meet", "paid": "pay", "sold": "sell", "spent": "spend", "took": "take",
    "data": "data", "analyses": "analysis", "indices": "index", "matrices": "matrix",
}


@dataclass
class Entity:
    text: str
    label: str


@dataclass
class Doc:
    """Backend-agnostic analysed document."""

    text: str
    sentences: list[str]
    tokens: list[str]
    lemmas: list[str]
    content_lemmas: list[str]
    noun_phrases: list[str]
    entities: list[Entity]
    backend: str

    def lemma_counts(self) -> Counter:
        return Counter(self.content_lemmas)


class NLPPipeline:
    """Text analysis with a spaCy fast path and a regex fallback."""

    # A single analysis re-reads the same resume and requirement text through
    # several scoring stages. Parsing is by far the most expensive step, so
    # analysed documents are memoised for the life of the process.
    _CACHE_LIMIT = 64

    def __init__(self) -> None:
        self._nlp = None
        self._cache: dict[str, Doc] = {}
        self.backend = "regex"
        self.backend_detail = "Rule-based pipeline (spaCy not active)"
        if settings.ENABLE_SPACY:
            self._try_load_spacy()

    def _try_load_spacy(self) -> None:
        try:
            import spacy  # type: ignore
        except Exception:
            return
        try:
            # Every component is used: tagger/attribute_ruler/lemmatizer for
            # lemmas, ner for entities, parser for noun chunks in job-description
            # keyword extraction. Nothing to disable.
            self._nlp = spacy.load(settings.SPACY_MODEL)
            self.backend = "spacy"
            self.backend_detail = f"spaCy {spacy.__version__} ({settings.SPACY_MODEL})"
        except Exception:
            # Model not downloaded - fall back to spaCy's blank English pipeline
            # for tokenisation only, which still beats the pure regex path.
            try:
                self._nlp = spacy.blank("en")
                self._nlp.add_pipe("sentencizer")
                self.backend = "spacy-blank"
                self.backend_detail = (
                    f"spaCy {spacy.__version__} blank English pipeline - run "
                    f"`python -m spacy download {settings.SPACY_MODEL}` for NER and lemmatisation"
                )
            except Exception:
                self._nlp = None

    # -- public API --------------------------------------------------------

    def info(self) -> dict[str, Any]:
        return {"backend": self.backend, "detail": self.backend_detail}

    def analyse(self, text: str) -> Doc:
        text = normalise_whitespace(text)
        if not text:
            return Doc("", [], [], [], [], [], [], self.backend)

        cached = self._cache.get(text)
        if cached is not None:
            return cached

        doc = self._analyse_spacy(text) if self._nlp is not None else self._analyse_regex(text)
        if len(self._cache) >= self._CACHE_LIMIT:
            self._cache.clear()  # simple bounded cache; analyses are short-lived
        self._cache[text] = doc
        return doc

    def lemmatise_many(self, words: Iterable[str]) -> dict[str, str]:
        """Lemmatise a bag of single words, batched.

        Calling ``analyse()`` once per word made keyword coverage the most
        expensive stage of the whole analysis - the per-call model overhead
        dominated while the words themselves were trivial. spaCy's own ``pipe``
        batches the model passes and keeps the word→lemma mapping exact, which
        joining the words into one string does not (``a/b`` and ``end-to-end``
        tokenise into several tokens).
        """
        unique = [w for w in dict.fromkeys(w.strip().lower() for w in words) if w]
        if not unique:
            return {}
        if self._nlp is None:
            return {word: simple_lemma(word) for word in unique}

        mapping: dict[str, str] = {}
        for word, doc in zip(unique, self._nlp.pipe(unique, batch_size=128)):
            lemma = next(
                ((token.lemma_ or token.text).lower() for token in doc if token.text.strip()),
                word,
            )
            mapping[word] = lemma
        return mapping

    # -- spaCy backend -----------------------------------------------------

    def _analyse_spacy(self, text: str) -> Doc:
        # spaCy's default max_length guard is generous, but resumes pasted with
        # artefacts can be huge - truncate rather than raise.
        doc = self._nlp(text[:200_000])
        tokens: list[str] = []
        lemmas: list[str] = []
        content: list[str] = []
        for tok in doc:
            if not tok.is_alpha and not any(ch.isalnum() for ch in tok.text):
                continue
            raw = tok.text.strip()
            if not raw:
                continue
            tokens.append(raw)
            lemma = (tok.lemma_ or raw).lower().strip()
            if not lemma:
                continue
            lemmas.append(lemma)
            if lemma not in STOPWORDS and len(lemma) > 1 and not lemma.isdigit():
                content.append(lemma)

        try:
            noun_phrases = [
                normalise_whitespace(np.text).lower()
                for np in doc.noun_chunks
                if 1 <= len(np.text.split()) <= 4
            ]
        except Exception:  # blank pipeline has no parser
            noun_phrases = _ngram_phrases(content)

        entities = [Entity(e.text.strip(), e.label_) for e in doc.ents]
        sentences = [s.text.strip() for s in doc.sents if s.text.strip()]
        if not entities:
            entities = _regex_entities(text)
        return Doc(text, sentences, tokens, lemmas, content, noun_phrases, entities, self.backend)

    # -- regex backend -----------------------------------------------------

    def _analyse_regex(self, text: str) -> Doc:
        sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
        tokens = _TOKEN_RE.findall(text)
        lemmas = [simple_lemma(t) for t in tokens]
        content = [
            lm for lm in lemmas if lm not in STOPWORDS and len(lm) > 1 and not lm.isdigit()
        ]
        return Doc(
            text,
            sentences,
            tokens,
            lemmas,
            content,
            _ngram_phrases(content),
            _regex_entities(text),
            self.backend,
        )

    # -- shared helpers ----------------------------------------------------

    def keywords(self, text: str, top_n: int = 30) -> list[tuple[str, int]]:
        """Frequency-ranked keyword phrases (unigrams + bigrams)."""
        doc = self.analyse(text)
        counter: Counter = Counter()
        counter.update(doc.content_lemmas)
        for phrase in doc.noun_phrases:
            cleaned = " ".join(w for w in phrase.split() if w not in STOPWORDS)
            if len(cleaned.split()) >= 2:
                counter[cleaned] += 2  # multi-word phrases are stronger signals
        for term, _count in list(counter.items()):
            if len(term) < 3:
                del counter[term]
        return counter.most_common(top_n)


# ---------------------------------------------------------------------------
# Module-level helpers (usable without instantiating the pipeline)
# ---------------------------------------------------------------------------


# PDF text layers store "fi", "fl", "ffi" and friends as single ligature
# glyphs. Left alone they silently break everything downstream: "Artiﬁcial
# Intelligence" never matches the ontology, "MLﬂow" becomes an unknown term, and
# a CS degree reads as a non-technical field of study.
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "ı": "i",
}
# Typographic punctuation that would otherwise split tokens or defeat matching.
_PUNCTUATION = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    " ": " ", " ": " ", " ": " ", "​": "",
    "﻿": "", "−": "-", "‐": "-", "‑": "-",
}


def normalise_whitespace(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for source, replacement in _LIGATURES.items():
        text = text.replace(source, replacement)
    for source, replacement in _PUNCTUATION.items():
        text = text.replace(source, replacement)
    text = text.replace("•", "\n- ").replace("●", "\n- ").replace("▪", "\n- ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def simple_lemma(token: str) -> str:
    """Lightweight suffix-stripping lemmatiser for the fallback backend."""
    low = token.lower()
    if low in _IRREGULAR_LEMMAS:
        return _IRREGULAR_LEMMAS[low]
    if len(low) <= 3:
        return low
    for suffix, repl in (
        ("ies", "y"), ("ied", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")
    ):
        if low.endswith(suffix) and len(low) - len(suffix) >= 3:
            stem = low[: len(low) - len(suffix)] + repl
            # crude doubling fix: "deployed" -> "deploy", "running" -> "run"
            if len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in "sl":
                stem = stem[:-1]
            return stem
    return low


def _ngram_phrases(content_lemmas: list[str], max_n: int = 3) -> list[str]:
    phrases: list[str] = []
    for n in (2, 3):
        if n > max_n:
            break
        for i in range(len(content_lemmas) - n + 1):
            window = content_lemmas[i : i + n]
            if all(w not in STOPWORDS for w in window):
                phrases.append(" ".join(window))
    return phrases


_ORG_HINT = re.compile(
    r"\b([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,3})\s+"
    r"(?:Inc|LLC|Ltd|Technologies|Systems|Solutions|Labs|University|Institute|College|Corporation|Corp)\b"
)
_DATE_HINT = re.compile(
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\b(?:19|20)\d{2}\b)"
)
_DEGREE_HINT = re.compile(
    r"\b(B\.?\s?Tech|B\.?E\.?|B\.?\s?Sc|Bachelor(?:'s)?|M\.?\s?Tech|M\.?\s?Sc|Master(?:'s)?|"
    r"MBA|Ph\.?D|Doctorate|Diploma|B\.?C\.?A|M\.?C\.?A)\b",
    re.IGNORECASE,
)


def _regex_entities(text: str) -> list[Entity]:
    ents: list[Entity] = []
    for m in _ORG_HINT.finditer(text):
        ents.append(Entity(m.group(0).strip(), "ORG"))
    for m in _DATE_HINT.finditer(text):
        ents.append(Entity(m.group(0).strip(), "DATE"))
    for m in _DEGREE_HINT.finditer(text):
        ents.append(Entity(m.group(0).strip(), "DEGREE"))
    seen: set[tuple[str, str]] = set()
    unique: list[Entity] = []
    for e in ents:
        key = (e.text.lower(), e.label)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[:80]


def find_metrics(text: str) -> list[str]:
    """Quantified results present in a piece of text."""
    return [m.group(0).strip() for m in _METRIC_RE.finditer(text or "")]


def has_metric(text: str) -> bool:
    return bool(_METRIC_RE.search(text or ""))


def find_years_of_experience(text: str) -> float:
    """Largest explicit 'N years' claim found in the text."""
    values = [float(m.group(1)) for m in _YEARS_RE.finditer(text or "")]
    return max(values) if values else 0.0


def first_word(text: str) -> str:
    match = re.search(r"[A-Za-z]+", text or "")
    return match.group(0).lower() if match else ""


@lru_cache(maxsize=1)
def get_pipeline() -> NLPPipeline:
    """Process-wide singleton - loading spaCy is expensive."""
    return NLPPipeline()
