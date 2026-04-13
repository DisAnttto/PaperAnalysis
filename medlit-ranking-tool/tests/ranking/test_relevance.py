"""Tests for app.ranking.relevance (ranking_spec §2.1)."""

from datetime import date

import pytest

from app.models.extraction import (
    DeviceExtraction,
    EvidenceDomainType,
    EvidenceStudyType,
    ExtractionResult,
    PaperSynopsis,
    StudyExtraction,
    TopicalRelevance,
)
from app.models.paper import Paper
from app.models.search import SearchRequest
from app.ranking.relevance import TOPICAL_RELEVANCE_LOOKUP, score_relevance


def _make_extraction(label: str) -> ExtractionResult:
    return ExtractionResult(
        paper_synopsis=PaperSynopsis(
            value="Synopsis.", supporting_evidence_snippets=["text"],
        ),
        topical_relevance=TopicalRelevance(
            label=label, evidence_snippet="text", evidence_section="abstract",
        ),
        device=DeviceExtraction(),
        study=StudyExtraction(
            study_type=EvidenceStudyType(
                value="unknown", evidence_snippet="text",
                evidence_section="abstract",
            ),
            evidence_domain=EvidenceDomainType(
                value="unknown", evidence_snippet="text",
                evidence_section="abstract",
            ),
        ),
    )


class TestScoreRelevance:
    def test_high_overlap_scores_high(
        self, paper: Paper, extraction: ExtractionResult,
        full_request: SearchRequest,
    ) -> None:
        score, bd = score_relevance(paper, extraction, full_request)
        assert 0.0 <= score <= 1.0
        assert score > 0.5
        assert "title_overlap" in bd["signals"]
        assert "abstract_overlap" in bd["signals"]
        assert "topical_relevance" in bd["signals"]

    def test_no_mesh_terms_redistributes_weights(
        self, paper: Paper, extraction: ExtractionResult,
    ) -> None:
        request = SearchRequest(query="stent outcomes", mesh_terms=[])
        score, bd = score_relevance(paper, extraction, request)
        assert "mesh_match" not in bd["signals"]
        weights = bd["weights"]
        assert "mesh_match" not in weights
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_topical_relevance_lookup_values(self) -> None:
        assert TOPICAL_RELEVANCE_LOOKUP["high"] == 1.0
        assert TOPICAL_RELEVANCE_LOOKUP["medium"] == 0.5
        assert TOPICAL_RELEVANCE_LOOKUP["low"] == 0.0

    def test_low_relevance_label_lowers_score(self, paper: Paper) -> None:
        ext_high = _make_extraction("high")
        ext_low = _make_extraction("low")
        req = SearchRequest(query="coronary stent")
        score_high, _ = score_relevance(paper, ext_high, req)
        score_low, _ = score_relevance(paper, ext_low, req)
        assert score_high > score_low

    def test_no_abstract_still_scores(self, extraction: ExtractionResult) -> None:
        paper = Paper(title="Coronary stent trial", abstract=None)
        req = SearchRequest(query="coronary stent")
        score, bd = score_relevance(paper, extraction, req)
        assert 0.0 <= score <= 1.0
        assert bd["signals"]["abstract_overlap"] == 0.0

    def test_score_bounded_zero_one(
        self, paper: Paper, extraction: ExtractionResult,
    ) -> None:
        req = SearchRequest(query="completely unrelated quantum physics topic")
        score, _ = score_relevance(paper, extraction, req)
        assert 0.0 <= score <= 1.0

    def test_deterministic(
        self, paper: Paper, extraction: ExtractionResult,
        full_request: SearchRequest,
    ) -> None:
        ref = date(2025, 1, 1)
        results = [
            score_relevance(
                paper, extraction, full_request, reference_date=ref,
            )
            for _ in range(5)
        ]
        scores = [r[0] for r in results]
        assert all(s == scores[0] for s in scores)


class TestRecencySignal:
    def test_weights_include_recency(
        self, paper: Paper, extraction: ExtractionResult, full_request: SearchRequest,
    ) -> None:
        _, bd = score_relevance(
            paper, extraction, full_request, reference_date=date(2025, 6, 1),
        )
        assert "recency" in bd["weights"]
        assert abs(bd["weights"]["recency"] - 0.10) < 1e-9

    def test_recency_tiers_with_fixed_reference(
        self, extraction: ExtractionResult,
    ) -> None:
        req = SearchRequest(query="stent")
        ref = date(2025, 6, 1)
        p_new = Paper(title="Recent", abstract="stent trial", published_date=date(2024, 1, 1))
        p_mid = Paper(title="Mid", abstract="stent trial", published_date=date(2022, 6, 1))
        p_old = Paper(title="Old", abstract="stent trial", published_date=date(2010, 1, 1))
        s_new, bd_new = score_relevance(p_new, extraction, req, reference_date=ref)
        s_mid, bd_mid = score_relevance(p_mid, extraction, req, reference_date=ref)
        s_old, bd_old = score_relevance(p_old, extraction, req, reference_date=ref)
        assert bd_new["signals"]["recency"] == 1.0
        assert bd_mid["signals"]["recency"] == 0.7
        assert bd_old["signals"]["recency"] == 0.1
        assert s_new > s_mid > s_old

    def test_missing_date_recency_zero(self, extraction: ExtractionResult) -> None:
        paper = Paper(title="No date", abstract="stent", published_date=None)
        _, bd = score_relevance(
            paper, extraction, SearchRequest(query="stent"),
            reference_date=date(2025, 1, 1),
        )
        assert bd["signals"]["recency"] == 0.0
