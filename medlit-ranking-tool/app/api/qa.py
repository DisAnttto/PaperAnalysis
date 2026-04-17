"""QA console: gold regression cases from ``tests/collection/cases.json``."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])

_CASES_PATH = Path(__file__).resolve().parent.parent.parent / "tests" / "collection" / "cases.json"


class GoldExpectationsOut(BaseModel):
    """Validation criteria returned to the frontend for client-side pass/fail checking."""

    golden_pmids: list[str] = Field(default_factory=list)
    min_composite_by_pmid: dict[str, float] = Field(default_factory=dict)
    max_rank_by_pmid: dict[str, int] = Field(default_factory=dict)
    min_m_nonzero_count: int | None = None
    max_glaucoma_procedure_in_top_n: list[int] | None = None


class GoldCaseOut(BaseModel):
    """Subset of a live-search case for the internal UI."""

    id: str
    name: str = ""
    description: str = ""
    request: dict = Field(default_factory=dict)
    golden_pmids: list[str] = Field(default_factory=list)
    expectations: GoldExpectationsOut = Field(default_factory=GoldExpectationsOut)


@router.get("/gold-cases")
async def list_gold_cases() -> dict:
    """Return all gold cases with full ``SearchRequest`` payloads for form fill."""
    if not _CASES_PATH.is_file():
        return {"cases": [], "source": None, "error": "cases.json not found"}

    raw = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    out: list[GoldCaseOut] = []
    for c in raw.get("cases", []):
        if not isinstance(c, dict) or "id" not in c:
            continue
        exp = c.get("expectations") or {}
        golden_pmids = list(exp.get("golden_pmids") or [])
        expectations = GoldExpectationsOut(
            golden_pmids=golden_pmids,
            min_composite_by_pmid={
                str(k): float(v)
                for k, v in (exp.get("min_composite_by_pmid") or {}).items()
            },
            max_rank_by_pmid={
                str(k): int(v)
                for k, v in (exp.get("max_rank_by_pmid") or {}).items()
            },
            min_m_nonzero_count=exp.get("min_m_nonzero_count"),
            max_glaucoma_procedure_in_top_n=exp.get("max_glaucoma_procedure_in_top_n"),
        )
        out.append(
            GoldCaseOut(
                id=c["id"],
                name=str(c.get("name") or c["id"]),
                description=str(c.get("description") or ""),
                request=c.get("request") or {},
                golden_pmids=golden_pmids,
                expectations=expectations,
            )
        )
    return {
        "cases": [x.model_dump(mode="json") for x in out],
        "source": str(_CASES_PATH),
    }
