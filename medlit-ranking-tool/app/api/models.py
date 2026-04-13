"""Shared response models for the MedLit API."""

from pydantic import BaseModel

from app.models.extraction import ExtractionResult
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper
from app.models.ranking import RankedPaperResponse


class SearchResponse(BaseModel):
    """Wrapper returned by POST /api/v1/search."""

    results: list[RankedPaperResponse]
    total: int
    mode: str      # "demo" or "live"
    query: str


class PaperDetailResponse(BaseModel):
    """Full paper detail including extraction and normalization, for the QA console."""

    paper: Paper
    extraction: ExtractionResult | None
    normalized: NormalizedProduct | None
    mode: str
