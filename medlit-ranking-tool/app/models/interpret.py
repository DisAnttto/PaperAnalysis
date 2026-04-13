"""Outcome interpretation workflow request/response models."""

from typing import Any

from pydantic import BaseModel, Field

from app.models.ranking import RankedPaperResponse
from app.models.search import TargetProductProfile


class ObservedFinding(BaseModel):
    """User's clinical observation to interpret."""

    metric_name: str  # e.g. "IOP"
    metric_unit: str | None = None  # e.g. "mmHg"
    timepoint: str | None = None  # e.g. "POD1", "Month 3"
    observed_value: float
    control_value: float | None = None
    difference_direction: str | None = None  # "higher" / "lower"
    p_value: float | None = None
    is_significant: bool | None = None
    clinical_context: str | None = None  # e.g. "cataract surgery"
    product_name: str | None = None
    product_type: str | None = None  # "device" / "drug"
    indication: str | None = None
    procedure: str | None = None  # e.g. "phacoemulsification"
    desired_angles: list[str] = Field(default_factory=list)


class InterpretRequest(BaseModel):
    finding: ObservedFinding
    target_product: TargetProductProfile | None = None
    max_results_per_angle: int = 5
    pool_size: int = 50


class InterpretationAngle(BaseModel):
    angle_id: str
    label: str
    description: str
    reasoning: str


class EvidenceClaim(BaseModel):
    claim_id: str
    angle_id: str
    claim_text: str
    search_query: str
    value_range: tuple[float, float] | None = None
    timepoint_filter: str | None = None
    metric_filter: str | None = None


class ClaimResult(BaseModel):
    claim: EvidenceClaim
    papers: list[RankedPaperResponse]
    claim_relevance_scores: dict[str, float]  # uid -> 0-1


class EvidencePackage(BaseModel):
    angle: InterpretationAngle
    claims: list[ClaimResult]
    strength: float
    summary: str


class InterpretResponse(BaseModel):
    finding: ObservedFinding
    angles: list[EvidencePackage]
    overall_summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)
