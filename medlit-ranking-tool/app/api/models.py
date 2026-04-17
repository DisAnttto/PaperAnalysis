"""Shared response models for the MedLit API."""

from typing import Any

from pydantic import BaseModel, Field

from app.models.extraction import ExtractionResult
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper
from app.models.ranking import RankedPaperResponse
from app.models.run_log import StageCounts


class SearchResponse(BaseModel):
    """Wrapper returned by POST /api/v1/search."""

    results: list[RankedPaperResponse]
    total: int
    mode: str      # "demo" or "live"
    query: str
    run_id: str | None = None
    stage_counts: StageCounts | None = None


class PaperDetailResponse(BaseModel):
    """Full paper detail including extraction and normalization, for the QA console."""

    paper: Paper
    extraction: ExtractionResult | None
    normalized: NormalizedProduct | None
    mode: str
