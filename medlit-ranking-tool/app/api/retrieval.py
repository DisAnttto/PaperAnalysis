"""API endpoints for correlated-evidence retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from app.retrieval.models import BenchmarkTarget, ExtractedTargetProfile, RetrievalResponse
from app.retrieval.pipeline import retrieve_correlated_evidence

router = APIRouter(prefix="/api/v1/retrieval", tags=["retrieval"])

_TARGETS_PATH = Path(__file__).parent.parent / "retrieval_bench" / "targets.json"


class CorrelateRequest(BaseModel):
    seed: str | None = None
    query: str | None = None
    profile: dict[str, Any] | None = None


@router.post("/correlate", response_model=RetrievalResponse)
async def correlate(request: CorrelateRequest) -> RetrievalResponse:
    """Run the correlated-evidence retrieval pipeline.

    Accepts an optional ``seed`` identifier (PMID, 510(k) K-number, NCT ID,
    etc.) and/or a free-text ``query``.  The effective seed passed to the
    pipeline is ``seed`` when provided, otherwise ``query``.  At least one of
    the two must be non-empty.
    """
    effective_seed = (request.seed or "").strip() or (request.query or "").strip()
    if not effective_seed:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'seed' or 'query' must be provided.",
        )

    profile_override: ExtractedTargetProfile | None = None
    if request.profile:
        filtered = {
            k: v
            for k, v in request.profile.items()
            if k in ExtractedTargetProfile.model_fields and v is not None
        }
        if filtered:
            profile_override = ExtractedTargetProfile(**filtered)
        logger.info(
            "Correlate: seed={!r}, profile_fields={}",
            effective_seed,
            list(filtered.keys()) if filtered else "(empty after filtering nulls)",
        )
    else:
        logger.info("Correlate: seed={!r}, no profile sent", effective_seed)

    return await retrieve_correlated_evidence(
        effective_seed, profile_override=profile_override
    )


@router.get("/benchmark/{target_id}", response_model=BenchmarkTarget)
async def get_benchmark_target(target_id: str) -> BenchmarkTarget:
    """Return a single benchmark target by ID from targets.json."""
    if not _TARGETS_PATH.exists():
        raise HTTPException(status_code=404, detail="targets.json not found")
    targets = json.loads(_TARGETS_PATH.read_text(encoding="utf-8"))
    for t in targets:
        if t.get("target_id") == target_id:
            return BenchmarkTarget(**t)
    raise HTTPException(status_code=404, detail=f"Target {target_id!r} not found")
