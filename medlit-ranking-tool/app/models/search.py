"""Search request models.

Matches the API contract in product_spec §4.4 and the ranking inputs
described in ranking_spec §§1-3.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DirectionMode(StrEnum):
    """Comparison mode for a target metric (ranking_spec §2.3)."""

    HIGHER_BETTER = "higher_better"
    LOWER_BETTER = "lower_better"
    RANGE_BEST = "range_best"
    CLOSER_BETTER = "closer_better"


class SubmissionType(StrEnum):
    """FDA submission pathway — selects preset composite and sub-signal weights."""

    K510 = "510k"
    PMA = "pma"
    DE_NOVO = "de_novo"


# Single source of truth for submission-type presets (composite + P sub-weights).
SUBMISSION_PRESETS: dict[str, dict] = {
    "510k": {
        "composite": {"R": 0.20, "P": 0.40, "M": 0.20, "E": 0.20},
        "device_sub_weights": {
            "intended_use": 0.25,
            "device_category": 0.15,
            "material_subtype": 0.12,
            "indications": 0.12,
            "energy_source": 0.08,
            "anatomical_site": 0.08,
            "device_class": 0.05,
            "product_name": 0.05,
            "key_features": 0.04,
            "manufacturer": 0.03,
            "sterilization": 0.03,
        },
        "drug_sub_weights": {
            "drug_ingredient": 0.30,
            "drug_class": 0.15,
            "drug_route": 0.10,
            "drug_formulation_features": 0.05,
            "drug_product_name": 0.05,
        },
    },
    "pma": {
        "composite": {"R": 0.15, "P": 0.20, "M": 0.30, "E": 0.35},
        "device_sub_weights": {
            "intended_use": 0.14,
            "device_category": 0.18,
            "material_subtype": 0.14,
            "indications": 0.16,
            "energy_source": 0.05,
            "anatomical_site": 0.10,
            "device_class": 0.02,
            "product_name": 0.08,
            "key_features": 0.06,
            "manufacturer": 0.05,
            "sterilization": 0.02,
        },
        "drug_sub_weights": {
            "drug_ingredient": 0.30,
            "drug_class": 0.15,
            "drug_route": 0.10,
            "drug_formulation_features": 0.05,
            "drug_product_name": 0.05,
        },
    },
    "de_novo": {
        "composite": {"R": 0.20, "P": 0.30, "M": 0.20, "E": 0.30},
        "device_sub_weights": {
            "intended_use": 0.20,
            "device_category": 0.16,
            "material_subtype": 0.12,
            "indications": 0.14,
            "energy_source": 0.08,
            "anatomical_site": 0.10,
            "device_class": 0.05,
            "product_name": 0.05,
            "key_features": 0.04,
            "manufacturer": 0.03,
            "sterilization": 0.03,
        },
        "drug_sub_weights": {
            "drug_ingredient": 0.30,
            "drug_class": 0.15,
            "drug_route": 0.10,
            "drug_formulation_features": 0.05,
            "drug_product_name": 0.05,
        },
    },
}


class TargetMetric(BaseModel):
    """A single user-supplied target metric with its comparison rule.

    The ranker matches ``metric_name_normalized`` against extracted metrics
    and applies the direction formula using the threshold / target / range
    values provided here.
    """

    metric_name_normalized: str = Field(min_length=1)
    direction: DirectionMode
    threshold: float | None = None
    target: float | None = None
    range_lo: float | None = None
    range_hi: float | None = None
    normalisation_range: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_direction_fields(self) -> "TargetMetric":
        match self.direction:
            case DirectionMode.HIGHER_BETTER | DirectionMode.LOWER_BETTER:
                if self.threshold is None:
                    raise ValueError(
                        f"'threshold' is required for direction={self.direction}"
                    )
            case DirectionMode.CLOSER_BETTER:
                if self.target is None:
                    raise ValueError(
                        "'target' is required for direction=closer_better"
                    )
            case DirectionMode.RANGE_BEST:
                if self.range_lo is None or self.range_hi is None:
                    raise ValueError(
                        "'range_lo' and 'range_hi' are required "
                        "for direction=range_best"
                    )
        return self


class TargetProductProfile(BaseModel):
    """User-supplied target profile for Product Similarity scoring
    (ranking_spec §2.2).

    Supports both device and drug targets.  ``target_type`` controls which
    sub-signals are activated during scoring.  At least one substantive field
    must be non-null for the dimension to be scored.

    Device fields expect canonical ophthalmology values (e.g.
    ``device_category="intraocular_lens"``, ``material_subtype="hydrophobic_acrylic"``).
    Drug fields expect canonical normalized values (e.g.
    ``active_ingredient="ranibizumab"``, ``drug_class="anti_vegf"``).
    """

    # --- Modality selector ---
    target_type: Literal["device", "drug", "both"] = "device"

    # --- Device fields ---
    product_name: str | None = None
    device_category: str | None = None
    manufacturer: str | None = None
    intended_use: str | None = None
    indications: list[str] = Field(default_factory=list)
    anatomical_site: str | None = None
    # Legacy raw material string — kept for backward compat
    material: str | None = None
    key_features: list[str] = Field(default_factory=list)
    # Structured material target (preferred over legacy `material`)
    material_family: str | None = None
    material_subtype: str | None = None
    material_features: list[str] = Field(default_factory=list)
    # Canonical targets for additional device sub-signals (normalized layer)
    energy_source: str | None = None
    device_class: str | None = None
    sterilization_method: str | None = None

    # --- Drug fields ---
    active_ingredient: str | None = None
    drug_class: str | None = None
    route: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "TargetProductProfile":
        has_value = (
            self.product_name is not None
            or self.device_category is not None
            or self.manufacturer is not None
            or self.intended_use is not None
            or len(self.indications) > 0
            or self.anatomical_site is not None
            or self.material is not None
            or len(self.key_features) > 0
            or self.material_family is not None
            or self.material_subtype is not None
            or len(self.material_features) > 0
            or self.energy_source is not None
            or self.device_class is not None
            or self.sterilization_method is not None
            or self.active_ingredient is not None
            or self.drug_class is not None
            or self.route is not None
        )
        if not has_value:
            raise ValueError(
                "TargetProductProfile requires at least one non-null field"
            )
        return self


class RankingWeights(BaseModel):
    """Custom dimension weights for the composite score (ranking_spec §3).

    Must sum to 1.0 (± 0.001) and all values must be >= 0.
    """

    R: float = Field(default=0.35, ge=0)
    P: float = Field(default=0.25, ge=0)
    M: float = Field(default=0.20, ge=0)
    E: float = Field(default=0.20, ge=0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "RankingWeights":
        total = self.R + self.P + self.M + self.E
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Weights must sum to 1.0 (± 0.001), got {total:.4f}"
            )
        return self


class SearchRequest(BaseModel):
    """Top-level request submitted to ``POST /api/v1/search``.

    Combines the search query, optional target product profile, optional
    target comparison metrics, and optional custom ranking weights.
    """

    query: str = Field(min_length=1)
    mesh_terms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    target_product: TargetProductProfile | None = None
    target_metrics: list[TargetMetric] = Field(default_factory=list)
    metrics_of_interest: list[str] = Field(
        default_factory=list,
        description=(
            "Metric names the user wants the LLM to prioritize extracting "
            "(e.g. 'BCVA', 'IOP', 'central retinal thickness'). "
            "Injected as hints into the extraction prompt; does not affect scoring."
        ),
    )
    weights: RankingWeights | None = None
    max_results: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Final number of papers after AI triage (full extraction runs on this many).",
    )
    pool_size: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of results to fetch from each database before AI triage.",
    )

    submission_type: SubmissionType | None = Field(
        default=None,
        description=(
            "FDA submission pathway. Sets preset composite and sub-signal weights."
        ),
    )
    similarity_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum composite score; papers below this are excluded from results."
        ),
    )

    # ── Search filters ────────────────────────────────────────────────────
    min_year: int | None = Field(default=None, ge=1900, le=2100, description="Earliest publication year (inclusive)")
    max_year: int | None = Field(default=None, ge=1900, le=2100, description="Latest publication year (inclusive)")
    country: str | None = Field(default=None, max_length=100, description="Filter by author affiliation country")

    # ── Post-retrieval filters (applied after pool, before triage) ───────
    journal_filter: list[str] = Field(
        default_factory=list,
        description="Include only papers from these journals (case-insensitive substring match).",
    )
    author_filter: list[str] = Field(
        default_factory=list,
        description="Include only papers with at least one matching author (case-insensitive substring).",
    )
    include_terms: list[str] = Field(
        default_factory=list,
        description="Paper must contain ALL of these terms in title or abstract (case-insensitive).",
    )
    exclude_terms: list[str] = Field(
        default_factory=list,
        description="Exclude papers containing ANY of these terms in title or abstract (case-insensitive).",
    )

    @model_validator(mode="after")
    def _apply_submission_preset(self) -> "SearchRequest":
        if self.submission_type and self.weights is None:
            preset = SUBMISSION_PRESETS[self.submission_type.value]
            cw = preset["composite"]
            self.weights = RankingWeights(R=cw["R"], P=cw["P"], M=cw["M"], E=cw["E"])
        return self

    @model_validator(mode="after")
    def _pool_covers_max_results(self) -> "SearchRequest":
        if self.pool_size < self.max_results:
            raise ValueError(
                f"pool_size ({self.pool_size}) must be >= max_results ({self.max_results})"
            )
        return self
