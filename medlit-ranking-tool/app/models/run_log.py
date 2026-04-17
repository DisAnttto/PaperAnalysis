"""PRISMA-style retrieval run log for observability and provenance."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StageCounts(BaseModel):
    """Per-stage record counts following a PRISMA-inspired flow."""

    pool_per_source: dict[str, int] = Field(default_factory=dict)
    pool_total: int = 0
    post_dedup: int = 0
    post_triage: int = 0
    post_extraction: int = 0
    final_ranked: int = 0


class RetrievalRunLog(BaseModel):
    """Immutable log of a single search/interpret run for reproducibility."""

    run_id: str
    query: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    mode: str = "live"
    stage_counts: StageCounts = Field(default_factory=StageCounts)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
