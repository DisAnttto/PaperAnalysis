"""Tests for app.ranking.composite (ranking_spec §§3-4).

Composite and rank_papers now require a precomputed NormalizedProduct.
All helpers that call score_composite or rank_papers pass a normalized arg.
"""

import asyncio
from datetime import date

import pytest

from app.models.extraction import (
    DeviceExtraction,
    EvidenceDomainType,
    EvidenceInt,
    EvidenceStr,
    EvidenceStrList,
    EvidenceStudyType,
    ExtractionResult,
    ExtractedMetric,
    PaperSynopsis,
    StudyExtraction,
    TopicalRelevance,
)
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper
from app.models.search import (
    RankingWeights,
    SearchRequest,
    SubmissionType,
    TargetMetric,
    TargetProductProfile,
)
from app.normalization import normalize_extraction
from app.ranking.composite import rank_papers, score_composite


def _sc(*args, **kwargs):
    return asyncio.run(score_composite(*args, **kwargs))


def _rp(*args, **kwargs):
    return asyncio.run(rank_papers(*args, **kwargs))


def _norm(ext: ExtractionResult) -> NormalizedProduct:
    return normalize_extraction(ext)


class TestAllDimensionsPresent:
    def test_composite_in_range(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
        full_request: SearchRequest,
    ) -> None:
        score, details = _sc(paper, extraction, normalized, full_request)
        assert 0.0 <= score <= 1.0
        assert details["dimensions_excluded"] == []
        for dim in ("R", "P", "M", "E"):
            assert 0.0 <= details["scores"][dim] <= 1.0

    def test_all_weights_active(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
        full_request: SearchRequest,
    ) -> None:
        _, details = _sc(paper, extraction, normalized, full_request)
        w = details["weights_used"]
        assert abs(w["R"] - 0.35) < 1e-9
        assert abs(w["P"] - 0.25) < 1e-9
        assert abs(w["M"] - 0.20) < 1e-9
        assert abs(w["E"] - 0.20) < 1e-9

    def test_rationale_non_empty(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
        full_request: SearchRequest,
    ) -> None:
        _, details = _sc(paper, extraction, normalized, full_request)
        assert len(details["ranking_rationale"]) > 0
        assert details["ranking_rationale"].endswith(".")


class TestMissingProductProfile:
    def test_p_excluded_and_weights_renormalized(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
        minimal_request: SearchRequest,
    ) -> None:
        _, details = _sc(paper, extraction, normalized, minimal_request)
        assert "P" in details["dimensions_excluded"]
        w = details["weights_used"]
        assert w["P"] == 0.0
        non_zero = {k: v for k, v in w.items() if v > 0}
        assert abs(sum(non_zero.values()) - 1.0) < 1e-9

    def test_p_score_is_zero(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
        minimal_request: SearchRequest,
    ) -> None:
        _, details = _sc(paper, extraction, normalized, minimal_request)
        assert details["scores"]["P"] == 0.0


class TestMissingMetrics:
    def test_m_excluded_when_no_targets(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
    ) -> None:
        request = SearchRequest(
            query="coronary stent",
            target_product=TargetProductProfile(device_category="coronary stent"),
        )
        _, details = _sc(paper, extraction, normalized, request)
        assert "M" in details["dimensions_excluded"]
        assert details["weights_used"]["M"] == 0.0

    def test_m_incomplete_when_no_match(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
    ) -> None:
        request = SearchRequest(
            query="coronary stent",
            target_metrics=[TargetMetric(
                metric_name_normalized="nonexistent_metric",
                direction="lower_better",
                threshold=10.0,
                normalisation_range=10.0,
            )],
        )
        _, details = _sc(paper, extraction, normalized, request)
        assert details["metric_score_incomplete"] is True
        assert details["scores"]["M"] == 0.0


class TestMissingStudyInfo:
    def test_evidence_score_estimated_flag(self, paper: Paper) -> None:
        extraction = ExtractionResult(
            paper_synopsis=PaperSynopsis(
                value="Synopsis.", supporting_evidence_snippets=["text"],
            ),
            topical_relevance=TopicalRelevance(
                label="medium", evidence_snippet="text",
                evidence_section="abstract",
            ),
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
        request = SearchRequest(query="test query")
        normalized = _norm(extraction)
        _, details = _sc(paper, extraction, normalized, request)
        assert details["evidence_score_estimated"] is True
        assert details["scores"]["E"] == 0.20


class TestWeightRenormalization:
    def test_excluding_p_and_m_renormalises_to_r_and_e(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
    ) -> None:
        request = SearchRequest(query="coronary stent")
        _, details = _sc(paper, extraction, normalized, request)
        assert "P" in details["dimensions_excluded"]
        assert "M" in details["dimensions_excluded"]
        w = details["weights_used"]
        assert w["P"] == 0.0
        assert w["M"] == 0.0
        assert abs(w["R"] + w["E"] - 1.0) < 1e-9
        expected_r = 0.35 / (0.35 + 0.20)
        expected_e = 0.20 / (0.35 + 0.20)
        assert abs(w["R"] - expected_r) < 1e-9
        assert abs(w["E"] - expected_e) < 1e-9

    def test_custom_weights_renormalise(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
    ) -> None:
        request = SearchRequest(
            query="stent",
            weights=RankingWeights(R=0.50, P=0.20, M=0.10, E=0.20),
        )
        _, details = _sc(paper, extraction, normalized, request)
        w = details["weights_used"]
        assert abs(w["R"] + w["E"] - 1.0) < 1e-9


class TestDeterminism:
    def test_identical_inputs_produce_identical_scores(
        self,
        paper: Paper,
        extraction: ExtractionResult,
        normalized: NormalizedProduct,
        full_request: SearchRequest,
    ) -> None:
        results = [
            _sc(paper, extraction, normalized, full_request)
            for _ in range(10)
        ]
        scores = [r[0] for r in results]
        assert all(s == scores[0] for s in scores)
        details_list = [r[1] for r in results]
        for d in details_list:
            assert d["scores"] == details_list[0]["scores"]


class TestRankPapers:
    def _make_paper(
        self, pmid: str, title: str, pub_date: date | None = None,
    ) -> Paper:
        return Paper(
            pmid=pmid, title=title, published_date=pub_date,
            abstract=f"Abstract for {title}.",
        )

    def _make_extraction(
        self, label: str, study_type: str, sample_size: int,
    ) -> ExtractionResult:
        return ExtractionResult(
            paper_synopsis=PaperSynopsis(
                value="Synopsis.", supporting_evidence_snippets=["text"],
            ),
            topical_relevance=TopicalRelevance(
                label=label, evidence_snippet="text",
                evidence_section="abstract",
            ),
            study=StudyExtraction(
                study_type=EvidenceStudyType(
                    value=study_type, evidence_snippet="text",
                    evidence_section="abstract",
                ),
                evidence_domain=EvidenceDomainType(
                    value="human_clinical", evidence_snippet="text",
                    evidence_section="abstract",
                ),
                sample_size=EvidenceInt(
                    value=sample_size, evidence_snippet=str(sample_size),
                    evidence_section="abstract",
                ),
            ),
        )

    def _make_tuple(self, pmid, title, label, study_type, n, pub_date=None):
        p = self._make_paper(pmid, title, pub_date)
        e = self._make_extraction(label, study_type, n)
        return p, e, _norm(e)

    def test_papers_sorted_by_composite_desc(self) -> None:
        t1 = self._make_tuple("1", "High quality RCT", "high", "rct", 1000)
        t2 = self._make_tuple("2", "Low quality case report", "low", "case_report", 5)
        request = SearchRequest(query="test query")
        results = _rp([t1, t2], request)
        assert len(results) == 2
        assert results[0].rank == 1
        assert results[1].rank == 2
        assert results[0].composite_score >= results[1].composite_score

    def test_rank_numbers_sequential(self) -> None:
        tuples = [
            self._make_tuple(str(i), f"Paper {i}", "medium", "rct", 100 + i * 50)
            for i in range(5)
        ]
        request = SearchRequest(query="test")
        results = _rp(tuples, request)
        ranks = [r.rank for r in results]
        assert ranks == [1, 2, 3, 4, 5]

    def test_tiebreak_by_evidence_then_date(self) -> None:
        t1 = self._make_tuple("1", "Paper A", "medium", "rct", 100, date(2023, 1, 1))
        t2 = self._make_tuple("2", "Paper A", "medium", "rct", 100, date(2024, 6, 1))
        request = SearchRequest(query="Paper A")
        results = _rp([t1, t2], request)
        assert results[0].published_date == date(2024, 6, 1)

    def test_response_has_all_fields(self) -> None:
        t = self._make_tuple("1", "Test paper", "high", "rct", 500)
        request = SearchRequest(query="test")
        results = _rp([t], request)
        r = results[0]
        assert r.rank == 1
        assert r.pmid == "1"
        assert 0.0 <= r.composite_score <= 1.0
        assert 0.0 <= r.relevance_score <= 1.0
        assert 0.0 <= r.evidence_quality_score <= 1.0
        assert isinstance(r.weights_used, dict)
        assert isinstance(r.dimensions_excluded, list)
        assert isinstance(r.ranking_rationale, str)


class TestSimilarityThreshold:
    def test_no_threshold_returns_all(self) -> None:
        rp = TestRankPapers()
        t1 = rp._make_tuple("1", "Paper A", "medium", "rct", 100)
        t2 = rp._make_tuple("2", "Paper B", "medium", "rct", 200)
        request = SearchRequest(query="test")
        results = _rp([t1, t2], request)
        assert len(results) == 2

    def test_papers_below_threshold_excluded(self) -> None:
        rp = TestRankPapers()
        t1 = rp._make_tuple("1", "Paper A", "medium", "rct", 100)
        t2 = rp._make_tuple("2", "Paper B", "medium", "rct", 200)
        request = SearchRequest(query="test", similarity_threshold=1.0)
        results = _rp([t1, t2], request)
        assert len(results) == 0


class TestSubmissionTypePresets:
    def test_510k_applies_preset_composite_weights(
        self, target_product: TargetProductProfile,
    ) -> None:
        req = SearchRequest(
            query="stent",
            target_product=target_product,
            submission_type=SubmissionType.K510,
        )
        assert req.weights is not None
        assert req.weights.P == pytest.approx(0.40)
        assert req.weights.R == pytest.approx(0.20)

    def test_pma_applies_preset_composite_weights(
        self, target_product: TargetProductProfile,
    ) -> None:
        req = SearchRequest(
            query="stent",
            target_product=target_product,
            submission_type=SubmissionType.PMA,
        )
        assert req.weights is not None
        assert req.weights.E == pytest.approx(0.35)
        assert req.weights.M == pytest.approx(0.30)

    def test_de_novo_applies_preset_composite_weights(
        self, target_product: TargetProductProfile,
    ) -> None:
        req = SearchRequest(
            query="stent",
            target_product=target_product,
            submission_type=SubmissionType.DE_NOVO,
        )
        assert req.weights is not None
        assert req.weights.P == pytest.approx(0.30)
        assert req.weights.E == pytest.approx(0.30)

    def test_submission_type_in_ranked_response(
        self,
    ) -> None:
        rp = TestRankPapers()
        t = rp._make_tuple("1", "Paper", "high", "rct", 500)
        req = SearchRequest(
            query="test",
            submission_type=SubmissionType.K510,
        )
        results = _rp([t], req)
        assert results[0].submission_type == "510k"
