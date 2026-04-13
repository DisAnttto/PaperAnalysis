"""Relevance scoring (ranking_spec §2.1).

Measures how closely a paper matches the user's search intent using five
sub-signals: title keyword overlap, abstract keyword overlap, MeSH/keyword
match, LLM topical relevance label, and publication recency.
"""

from datetime import date

from app.models.extraction import ExtractionResult, TopicalRelevanceLabel
from app.models.paper import Paper
from app.models.search import SearchRequest

TOPICAL_RELEVANCE_LOOKUP: dict[str, float] = {
    TopicalRelevanceLabel.HIGH: 1.0,
    TopicalRelevanceLabel.MEDIUM: 0.5,
    TopicalRelevanceLabel.LOW: 0.0,
}

_SUB_WEIGHTS: dict[str, float] = {
    "title_overlap": 0.25,
    "abstract_overlap": 0.25,
    "mesh_match": 0.25,
    "topical_relevance": 0.15,
    "recency": 0.10,
}


def _tokenize(text: str) -> set[str]:
    return set(text.lower().split())


def _recall(query: set[str], text: set[str]) -> float:
    """Fraction of query tokens found in text.

    Unlike Jaccard, this does not penalise the paper for containing words
    beyond the query terms, which is always the case for titles/abstracts.
    A paper that contains every query keyword scores 1.0 regardless of length.
    """
    if not query or not text:
        return 0.0
    return len(query & text) / len(query)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


def _build_query_tokens(request: SearchRequest) -> set[str]:
    """Combine query, keywords, and mesh_terms into a single token set."""
    tokens: set[str] = set()
    tokens |= _tokenize(request.query)
    for kw in request.keywords:
        tokens |= _tokenize(kw)
    for term in request.mesh_terms:
        tokens |= _tokenize(term)
    return tokens


def recency_component(
    paper: Paper,
    *,
    reference_date: date | None = None,
) -> float:
    """Deterministic recency tier ∈ [0, 1] for blending with LLM relevance."""
    ref = reference_date if reference_date is not None else date.today()
    return _recency_signal(paper.published_date, ref)


def _recency_signal(
    published: date | None,
    reference: date,
) -> float:
    """FDA-style preference for recent evidence (tiered decay).

    Unknown publication date scores 0.0.
    """
    if published is None:
        return 0.0
    years = (reference - published).days / 365.25
    if years <= 2.0:
        return 1.0
    if years <= 5.0:
        return 0.7
    if years <= 10.0:
        return 0.4
    return 0.1


def score_relevance(
    paper: Paper,
    extracted: ExtractionResult,
    request: SearchRequest,
    *,
    reference_date: date | None = None,
) -> tuple[float, dict]:
    """Compute the relevance score R ∈ [0, 1].

    Returns (score, breakdown) where breakdown contains each sub-signal
    value and the effective weights used.

    ``reference_date`` defaults to today's date (for recency tiers); tests
    may pass a fixed date for determinism.
    """
    ref = reference_date if reference_date is not None else date.today()

    signals: dict[str, float] = {}
    active_weights: dict[str, float] = {}

    query_tokens = _build_query_tokens(request)
    has_query_tokens = len(query_tokens) > 0

    if has_query_tokens:
        title_tokens = _tokenize(paper.title)
        signals["title_overlap"] = _recall(query_tokens, title_tokens)
        active_weights["title_overlap"] = _SUB_WEIGHTS["title_overlap"]

        abstract_tokens = _tokenize(paper.abstract) if paper.abstract else set()
        signals["abstract_overlap"] = _recall(query_tokens, abstract_tokens)
        active_weights["abstract_overlap"] = _SUB_WEIGHTS["abstract_overlap"]

    query_mesh = {t.lower() for t in request.mesh_terms}
    if query_mesh:
        paper_mesh = {t.lower() for t in paper.mesh_terms}
        matched = len(query_mesh & paper_mesh)
        signals["mesh_match"] = matched / len(query_mesh)
        active_weights["mesh_match"] = _SUB_WEIGHTS["mesh_match"]

    label = extracted.topical_relevance.label
    signals["topical_relevance"] = TOPICAL_RELEVANCE_LOOKUP.get(label, 0.0)
    active_weights["topical_relevance"] = _SUB_WEIGHTS["topical_relevance"]

    signals["recency"] = _recency_signal(paper.published_date, ref)
    active_weights["recency"] = _SUB_WEIGHTS["recency"]

    total_weight = sum(active_weights.values())
    if total_weight == 0:
        return 0.0, {"signals": signals, "weights": {}, "note": "no scoreable sub-signals"}

    normalised_weights = {k: v / total_weight for k, v in active_weights.items()}
    score = sum(signals[k] * normalised_weights[k] for k in signals)
    score = max(0.0, min(1.0, score))

    return score, {
        "signals": signals,
        "weights": normalised_weights,
        "reference_date": ref.isoformat(),
    }
