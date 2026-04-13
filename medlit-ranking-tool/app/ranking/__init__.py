"""Public API for the ranking module."""

from app.ranking.composite import rank_papers, score_composite
from app.ranking.evidence_quality import score_evidence_quality
from app.ranking.metric_favorability import score_metric_favorability
from app.ranking.product_similarity import score_product_similarity
from app.ranking.relevance import score_relevance

__all__ = [
    "rank_papers",
    "score_composite",
    "score_evidence_quality",
    "score_metric_favorability",
    "score_product_similarity",
    "score_relevance",
]
