"""Post-normalization intermediate models consumed by the scorer.

These models are populated by ``app.normalization`` after LLM extraction and
passed directly to the product similarity scorer.  They are never produced
by the LLM; they contain only derived, deterministically normalized fields.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.normalization.registry import NormalizationMethod


class NormalizedMaterial(BaseModel):
    """Canonical material after ophthalmology normalization."""

    model_config = ConfigDict(extra="forbid")

    raw: str
    family: str | None = None
    subtype: str | None = None
    features: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    method: NormalizationMethod


class NormalizedDrug(BaseModel):
    """Canonical drug after ophthalmology normalization."""

    model_config = ConfigDict(extra="forbid")

    product_name_raw: str | None = None
    active_ingredient_raw: str | None = None
    active_ingredient_normalized: str | None = None
    drug_class_normalized: str | None = None
    route_normalized: str | None = None
    formulation_features_normalized: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    method: NormalizationMethod


class NormalizedDevice(BaseModel):
    """Canonical device after ophthalmology normalization."""

    model_config = ConfigDict(extra="forbid")

    product_name_raw: str | None = None
    device_category_raw: str | None = None
    device_category_normalized: str | None = None
    manufacturer_raw: str | None = None
    intended_use_raw: str | None = None
    intended_use_normalized: str | None = None
    indications_raw: list[str] = Field(default_factory=list)
    indications_normalized: list[str] = Field(default_factory=list)
    anatomical_site_raw: str | None = None
    anatomical_site_normalized: str | None = None
    material: NormalizedMaterial | None = None
    key_features_raw: list[str] = Field(default_factory=list)
    key_features_normalized: list[str] = Field(default_factory=list)
    device_class: str | None = None
    energy_source_normalized: str | None = None
    sterilization_normalized: str | None = None
    confidence: float = Field(ge=0, le=1)
    method: NormalizationMethod


class NormalizedProduct(BaseModel):
    """Post-normalization container passed to the product similarity scorer.

    ``product_type`` is derived by the normalization pipeline based on which
    sections were present in the extraction result.  The scorer uses it
    together with ``TargetProductProfile.target_type`` to select relevant
    sub-signals.
    """

    model_config = ConfigDict(extra="forbid")

    device: NormalizedDevice | None = None
    drug: NormalizedDrug | None = None
    product_type: Literal["device", "drug", "both", "unknown"] = "unknown"
