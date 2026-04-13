"""Paper-centric endpoints: metadata, extraction, ranking, and detail."""

from fastapi import APIRouter, HTTPException

from app.api.models import PaperDetailResponse
from app.core.config import settings
from app.models.extraction import ExtractionResult
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper
from app.normalization import normalize_extraction

router = APIRouter(prefix="/api/v1/papers", tags=["papers"])


def _get_paper(pmid: str) -> Paper:
    if settings.APP_MODE == "demo":
        from app.demo.fixtures import get_demo_paper
        paper = get_demo_paper(pmid)
        if paper is None:
            raise HTTPException(status_code=404, detail=f"Paper {pmid!r} not found in demo fixtures.")
        return paper

    from app.services.db import load_paper
    paper = load_paper(pmid)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {pmid!r} not found.")
    return paper


def _get_extraction(pmid: str) -> ExtractionResult | None:
    if settings.APP_MODE == "demo":
        from app.demo.fixtures import get_demo_extraction
        return get_demo_extraction(pmid)

    from app.services.db import load_extraction
    return load_extraction(pmid)


def _get_normalized(pmid: str) -> NormalizedProduct | None:
    if settings.APP_MODE == "demo":
        from app.demo.fixtures import get_demo_normalized
        return get_demo_normalized(pmid)

    from app.services.db import load_normalization
    return load_normalization(pmid)


@router.get("/{pmid}", response_model=Paper)
async def get_paper(pmid: str) -> Paper:
    """Return stored paper metadata."""
    return _get_paper(pmid)


@router.post("/{pmid}/extract", response_model=ExtractionResult)
async def run_extraction(pmid: str) -> ExtractionResult:
    """Return extraction result for a paper.

    In demo mode: returns the seeded extraction.
    In live mode: runs LLM extraction (or returns cached result).
    """
    paper = _get_paper(pmid)

    extraction = _get_extraction(pmid)
    if extraction is not None:
        return extraction

    # Live extraction
    from app.services.extraction import extract_paper as llm_extract
    from app.services.db import save_extraction, save_normalization

    extraction = await llm_extract(paper)
    save_extraction(pmid, extraction)

    normalized = normalize_extraction(extraction)
    save_normalization(pmid, normalized)

    return extraction


@router.get("/{pmid}/detail", response_model=PaperDetailResponse)
async def get_paper_detail(pmid: str) -> PaperDetailResponse:
    """Return full paper detail: metadata + extraction + normalized product."""
    paper = _get_paper(pmid)
    extraction = _get_extraction(pmid)
    normalized = _get_normalized(pmid)
    return PaperDetailResponse(
        paper=paper,
        extraction=extraction,
        normalized=normalized,
        mode=settings.APP_MODE,
    )
