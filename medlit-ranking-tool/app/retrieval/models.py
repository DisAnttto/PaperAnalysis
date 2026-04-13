"""Pydantic models for the correlated-evidence retrieval system."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.retrieval.enums import RelationLabel, SourceType, TierLevel


class SeedRecord(BaseModel):
    source_type: SourceType
    source_name: str
    identifier: str
    url: str | None = None
    title: str | None = None


class ExtractedTargetProfile(BaseModel):
    product_type: str
    submission_mode: str | None = None
    product_name: str | None = None
    active_ingredient: str | None = None
    route: str | None = None
    indication: list[str] = []
    key_metrics_or_endpoints: list[str] = []
    key_thresholds: list[str] = []


class EvidenceRecord(BaseModel):
    identifier: str
    source_type: SourceType
    source_name: str
    url: str | None = None
    title: str | None = None
    product_name: str | None = None
    manufacturer: str | None = None
    indication: list[str] = []
    route: str | None = None
    endpoints: list[str] = []
    raw_payload: dict[str, Any] | None = None


class GoldListEntry(BaseModel):
    tier: TierLevel
    rank_expectation: int | None = None
    source_type: SourceType
    identifier: str
    url: str | None = None
    relation_label: RelationLabel
    correlation_score: float | None = None
    evidence_strength_score: float | None = None
    explanation_value_score: float | None = None
    rationale: str = ""


class BenchmarkTarget(BaseModel):
    benchmark_version: str
    target_id: str
    seed: SeedRecord
    extracted_target_profile: ExtractedTargetProfile
    gold_list: list[GoldListEntry] = []


class CorrelationResult(BaseModel):
    candidate: EvidenceRecord
    correlation_score: float
    evidence_strength_score: float
    explanation_value_score: float
    relation_label: RelationLabel
    tier: TierLevel = TierLevel.Tier5
    matched_features: dict[str, float] = {}
    rationale: str = ""


class RetrievalResponse(BaseModel):
    seed: SeedRecord
    results: list[CorrelationResult] = []
    total_candidates_considered: int = 0
    metadata: dict[str, Any] = {}
