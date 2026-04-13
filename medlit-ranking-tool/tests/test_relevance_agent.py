"""Unit tests for LLM relevance agent + merge fallback."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.models.extraction import (
    EvidenceDomainType,
    EvidenceStudyType,
    ExtractionResult,
    PaperSynopsis,
    StudyExtraction,
    TopicalRelevance,
)
from app.models.paper import Paper
from app.models.search import SearchRequest
from app.ranking.relevance_agent import (
    llm_relevance_raw,
    merge_relevance_llm,
)


def _minimal_extraction() -> ExtractionResult:
    return ExtractionResult(
        paper_synopsis=PaperSynopsis(value="x", supporting_evidence_snippets=["x"]),
        topical_relevance=TopicalRelevance(
            label="high",
            evidence_snippet="x",
            evidence_section="title",
        ),
        study=StudyExtraction(
            study_type=EvidenceStudyType(
                value="rct",
                evidence_snippet="rct",
                evidence_section="abstract",
            ),
            evidence_domain=EvidenceDomainType(
                value="human_clinical",
                evidence_snippet="x",
                evidence_section="abstract",
            ),
        ),
    )


def test_llm_relevance_raw_parses_json():
    paper = Paper(
        pmid="1",
        title="Test",
        abstract="Abstract about lenses.",
    )
    req = SearchRequest(query="lens cataract")

    async def _run():
        with patch(
            "app.ranking.relevance_agent._call_relevance_llm",
            new_callable=AsyncMock,
            return_value='{"score": 0.85, "rationale": "Matches query."}',
        ):
            return await llm_relevance_raw(paper, req)

    out = asyncio.run(_run())
    assert out is not None
    s, bd = out
    assert s == pytest.approx(0.85)
    assert bd.get("method") == "llm"


def test_merge_relevance_llm_uses_blend_when_llm_ok():
    paper = Paper(pmid="1", title="t", abstract="a")
    ext = _minimal_extraction()
    req = SearchRequest(query="test")
    llm = (0.8, {"llm_score": 0.8, "rationale": "ok", "method": "llm"})
    r, bd = merge_relevance_llm(llm, paper, ext, req)
    assert 0.0 <= r <= 1.0
    assert bd.get("method") == "llm_recency_blend"
    assert "recency" in bd


def test_merge_relevance_llm_falls_back_when_none():
    paper = Paper(
        pmid="1",
        title="drug-eluting coronary stent outcomes",
        abstract="stent trial",
        mesh_terms=["Coronary Stents"],
    )
    ext = _minimal_extraction()
    req = SearchRequest(query="coronary stent", mesh_terms=["Coronary Stents"])
    r, bd = merge_relevance_llm(None, paper, ext, req)
    assert 0.0 <= r <= 1.0
    assert "signals" in bd
