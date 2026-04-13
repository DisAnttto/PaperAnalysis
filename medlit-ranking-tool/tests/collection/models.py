"""Pydantic models for the live search testing collection (cases.json)."""

from pathlib import Path

from pydantic import BaseModel, Field

from app.models.search import SearchRequest


class CaseExpectations(BaseModel):
    """Assertions applied to POST /api/v1/search results for a case."""

    golden_pmids: list[str] = Field(
        default_factory=list,
        description="PMIDs that must appear in the ranked results list.",
    )
    min_composite_by_pmid: dict[str, float] = Field(
        default_factory=dict,
        description="Minimum composite score per PMID when present in results.",
    )
    max_rank_by_pmid: dict[str, int] = Field(
        default_factory=dict,
        description="Maximum 1-based rank allowed for each PMID (inclusive).",
    )


class LiveSearchCase(BaseModel):
    """One regression case: validated SearchRequest + expectations."""

    id: str = Field(min_length=1)
    name: str = ""
    description: str = ""
    request: SearchRequest
    expectations: CaseExpectations = Field(default_factory=CaseExpectations)


class CollectionFile(BaseModel):
    """Root object in cases.json."""

    version: int = 1
    cases: list[LiveSearchCase] = Field(default_factory=list)


def default_cases_path() -> Path:
    return Path(__file__).resolve().parent / "cases.json"
