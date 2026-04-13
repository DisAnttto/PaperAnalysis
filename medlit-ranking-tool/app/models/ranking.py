"""Ranked paper response model.

Matches the output contract defined in ranking_spec §4.  Every paper in the
response carries its composite score, per-dimension scores, transparency
flags, and a deterministic rationale string.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class RankedPaperResponse(BaseModel):
    """A single paper in a ranked result set.

    Includes enough paper metadata for display and full scoring
    transparency as required by ranking_spec §4.
    """

    # --- Paper identity (from stored Paper metadata) ---
    pmid: str | None = None
    doi: str | None = None
    title: str
    abstract: str | None = None
    journal: str | None = None
    published_date: date | None = None

    # --- Rank and composite ---
    rank: int = Field(ge=1)
    composite_score: float = Field(ge=0, le=1)

    submission_type: str | None = None

    # --- Per-dimension scores (each ∈ [0, 1]) ---
    relevance_score: float = Field(ge=0, le=1)
    product_similarity_score: float = Field(ge=0, le=1)
    metric_favorability_score: float = Field(ge=0, le=1)
    evidence_quality_score: float = Field(ge=0, le=1)

    evidence_breakdown: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Deterministic breakdown from score_evidence_quality "
            "(base_score, size_modifier, follow_up_modifier, domain cap, etc.)."
        ),
    )
    metric_favorability_breakdown: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Breakdown from score_metric_favorability (matched/unmatched, "
            "coverage_mode, coverage_ratio). Aligns UI chips with the M score."
        ),
    )

    # --- Weights actually applied after renormalisation ---
    weights_used: dict[str, float]

    # --- Transparency flags ---
    dimensions_excluded: list[str] = Field(default_factory=list)
    metric_score_estimated: bool = False
    metric_score_incomplete: bool = False
    evidence_score_estimated: bool = False

    # --- Human-readable rationale (deterministic, not LLM-generated) ---
    ranking_rationale: str = ""

    # --- Summary labels for rich table display ---
    relevance_label: str | None = None
    product_label: str | None = None
    evidence_label: str | None = None
    extracted_metrics: list[dict] = Field(default_factory=list)
