"""Unit tests for the outcome interpretation orchestrator (Step 2: core logic)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.extraction import ExtractionResult, ExtractedMetric
from app.models.interpret import (
    ClaimResult,
    EvidenceClaim,
    EvidencePackage,
    InterpretationAngle,
    InterpretRequest,
    InterpretResponse,
    ObservedFinding,
)
from app.models.paper import Paper
from app.models.ranking import RankedPaperResponse
from app.services.interpret import (
    _CLAIM_TEMPLATES,
    _decompose_claims,
    _group_into_packages,
    _mean,
    _score_claim_relevance,
    interpret_finding,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _finding(
    metric: str = "IOP",
    unit: str = "mmHg",
    value: float = 20.0,
    timepoint: str = "POD1",
    procedure: str = "phacoemulsification",
    clinical_context: str = "cataract surgery",
) -> ObservedFinding:
    return ObservedFinding(
        metric_name=metric,
        metric_unit=unit,
        observed_value=value,
        timepoint=timepoint,
        procedure=procedure,
        clinical_context=clinical_context,
        p_value=0.03,
        is_significant=True,
    )


def _angle(angle_id: str) -> InterpretationAngle:
    return InterpretationAngle(
        angle_id=angle_id,
        label=angle_id.replace("_", " ").title(),
        description=f"Test angle: {angle_id}",
        reasoning="test",
    )


def _paper(pmid: str, title: str = "Test Paper") -> Paper:
    return Paper(pmid=pmid, source="PubMed", title=title)


def _extraction(
    pmid: str,
    metric_name: str = "IOP",
    numeric_value: float | None = 20.0,
    timepoint: str | None = "POD1",
) -> ExtractionResult:
    """Minimal ExtractionResult for testing claim-relevance scoring."""
    metric = MagicMock(spec=ExtractedMetric)
    metric.metric_name = metric_name
    metric.numeric_value = numeric_value
    metric.timepoint = timepoint

    ext = MagicMock(spec=ExtractionResult)
    ext.metrics = [metric]
    return ext


def _ranked(pmid: str, composite: float = 0.5, eq: float = 0.6) -> RankedPaperResponse:
    return RankedPaperResponse(
        pmid=pmid,
        title=f"Paper {pmid}",
        rank=1,
        composite_score=composite,
        relevance_score=0.5,
        product_similarity_score=0.0,
        metric_favorability_score=0.0,
        evidence_quality_score=eq,
        weights_used={"R": 0.4, "P": 0.2, "M": 0.2, "E": 0.2},
    )


# ---------------------------------------------------------------------------
# TestClaimDecomposition
# ---------------------------------------------------------------------------

class TestClaimDecomposition:
    """Template-based decomposition for known angle types."""

    def test_known_angle_ids_are_in_templates(self):
        expected = {
            "transient_recovery",
            "value_precedent",
            "acceptable_range",
            "statistical_not_clinical",
            "risk_signal",
            "mechanism_expected",
        }
        assert expected == set(_CLAIM_TEMPLATES.keys())

    @pytest.mark.parametrize("angle_id", list(_CLAIM_TEMPLATES.keys()))
    def test_template_returns_claims(self, angle_id: str):
        finding = _finding()
        angle = _angle(angle_id)
        fn = _CLAIM_TEMPLATES[angle_id]
        claims = fn(angle, finding, 0)
        assert len(claims) >= 1
        for c in claims:
            assert c.angle_id == angle_id
            assert c.search_query
            assert finding.metric_name in c.search_query

    def test_value_precedent_sets_value_range(self):
        finding = _finding(value=20.0)
        claims = _CLAIM_TEMPLATES["value_precedent"](_angle("value_precedent"), finding, 0)
        assert claims[0].value_range == (18.0, 22.0)
        assert claims[0].metric_filter == "IOP"
        assert claims[0].timepoint_filter == "POD1"

    def test_acceptable_range_returns_two_claims(self):
        claims = _CLAIM_TEMPLATES["acceptable_range"](_angle("acceptable_range"), _finding(), 0)
        assert len(claims) == 2
        assert claims[0].claim_id.endswith("_a")
        assert claims[1].claim_id.endswith("_b")

    def test_transient_recovery_sets_filters(self):
        finding = _finding()
        claims = _CLAIM_TEMPLATES["transient_recovery"](_angle("transient_recovery"), finding, 0)
        assert claims[0].metric_filter == "IOP"
        assert claims[0].timepoint_filter == "POD1"
        assert "transient" in claims[0].search_query.lower()

    @pytest.mark.asyncio
    async def test_known_angles_use_no_llm(self):
        finding = _finding()
        angles = [_angle(aid) for aid in ["transient_recovery", "value_precedent", "risk_signal"]]
        # No LLM patch needed — all known angles should produce claims without calling the LLM
        with patch("app.services.interpret._novel_angle_query") as mock_llm:
            claims = await _decompose_claims(angles, finding)
        mock_llm.assert_not_called()
        assert len(claims) >= 3

    @pytest.mark.asyncio
    async def test_novel_angle_triggers_light_model(self):
        finding = _finding()
        novel = InterpretationAngle(
            angle_id="some_novel_angle",
            label="Novel",
            description="A novel angle",
            reasoning="test",
        )
        with patch(
            "app.services.interpret._novel_angle_query",
            new_callable=AsyncMock,
            return_value='"IOP" AND "novel"',
        ) as mock_llm:
            claims = await _decompose_claims([novel], finding)
        mock_llm.assert_called_once()
        assert claims[0].angle_id == "some_novel_angle"
        assert '"IOP" AND "novel"' == claims[0].search_query


# ---------------------------------------------------------------------------
# TestClaimRelevanceScoring
# ---------------------------------------------------------------------------

class TestClaimRelevanceScoring:
    def test_all_signals_match(self):
        claim = EvidenceClaim(
            claim_id="c1", angle_id="a1", claim_text="t",
            search_query="q",
            metric_filter="IOP",
            value_range=(18.0, 22.0),
            timepoint_filter="POD1",
        )
        paper = _paper("1")
        ext = _extraction("1", metric_name="IOP", numeric_value=20.0, timepoint="POD1")
        scores = _score_claim_relevance(claim, [(paper, ext)])
        assert scores["1"] == pytest.approx(1.0)

    def test_no_signals_set_gives_zero_denominator_default(self):
        claim = EvidenceClaim(
            claim_id="c1", angle_id="a1", claim_text="t", search_query="q",
        )
        paper = _paper("2")
        ext = _extraction("2")
        scores = _score_claim_relevance(claim, [(paper, ext)])
        assert scores["2"] == pytest.approx(0.0)

    def test_metric_mismatch_scores_zero(self):
        claim = EvidenceClaim(
            claim_id="c1", angle_id="a1", claim_text="t", search_query="q",
            metric_filter="BCVA",
        )
        paper = _paper("3")
        ext = _extraction("3", metric_name="IOP")
        scores = _score_claim_relevance(claim, [(paper, ext)])
        assert scores["3"] == pytest.approx(0.0)

    def test_value_out_of_range_scores_partial(self):
        claim = EvidenceClaim(
            claim_id="c1", angle_id="a1", claim_text="t", search_query="q",
            metric_filter="IOP",
            value_range=(18.0, 22.0),
        )
        paper = _paper("4")
        ext = _extraction("4", metric_name="IOP", numeric_value=30.0)
        scores = _score_claim_relevance(claim, [(paper, ext)])
        # metric matched (0.5) but value out of range (0.0) → 0.5 / 2 = 0.5
        assert scores["4"] == pytest.approx(0.5)

    def test_timepoint_partial_match(self):
        claim = EvidenceClaim(
            claim_id="c1", angle_id="a1", claim_text="t", search_query="q",
            metric_filter="IOP",
            timepoint_filter="POD1",
        )
        paper = _paper("5")
        # timepoint contains "pod1" substring (case-insensitive)
        ext = _extraction("5", metric_name="IOP", timepoint="POD1-day-1")
        scores = _score_claim_relevance(claim, [(paper, ext)])
        assert scores["5"] == pytest.approx(1.0)

    def test_empty_pairs_returns_empty(self):
        claim = EvidenceClaim(
            claim_id="c1", angle_id="a1", claim_text="t", search_query="q",
            metric_filter="IOP",
        )
        assert _score_claim_relevance(claim, []) == {}


# ---------------------------------------------------------------------------
# TestGroupIntoPackages
# ---------------------------------------------------------------------------

class TestGroupIntoPackages:
    def _make_claim_result(self, angle_id: str, pmids: list[str]) -> ClaimResult:
        papers = [_ranked(pmid) for pmid in pmids]
        scores = {pmid: 0.8 for pmid in pmids}
        claim = EvidenceClaim(
            claim_id=f"{angle_id}_0", angle_id=angle_id,
            claim_text="t", search_query="q",
        )
        return ClaimResult(claim=claim, papers=papers, claim_relevance_scores=scores)

    def test_groups_by_angle(self):
        angles = [_angle("value_precedent"), _angle("acceptable_range")]
        cr1 = self._make_claim_result("value_precedent", ["1", "2"])
        cr2 = self._make_claim_result("acceptable_range", ["3"])
        packages = _group_into_packages(angles, [cr1, cr2])
        assert len(packages) == 2
        assert packages[0].angle.angle_id == "value_precedent"
        assert packages[1].angle.angle_id == "acceptable_range"

    def test_strength_is_mean_relevance(self):
        angles = [_angle("risk_signal")]
        cr = self._make_claim_result("risk_signal", ["1", "2"])
        # all relevance scores are 0.8
        packages = _group_into_packages(angles, [cr])
        assert packages[0].strength == pytest.approx(0.8)

    def test_missing_angle_gets_empty_package(self):
        angles = [_angle("transient_recovery"), _angle("risk_signal")]
        cr = self._make_claim_result("risk_signal", ["1"])
        packages = _group_into_packages(angles, [cr])
        transient_pkg = next(p for p in packages if p.angle.angle_id == "transient_recovery")
        assert transient_pkg.claims == []
        assert transient_pkg.strength == pytest.approx(0.0)

    def test_summary_placeholder_is_empty(self):
        angles = [_angle("value_precedent")]
        cr = self._make_claim_result("value_precedent", ["1"])
        packages = _group_into_packages(angles, [cr])
        assert packages[0].summary == ""

    def test_papers_resorted_by_blended_score(self):
        angles = [_angle("value_precedent")]
        # paper "low" has high claim_relevance=1.0 but low composite/eq
        # paper "high" has claim_relevance=0.0 but high composite/eq
        low = _ranked("low", composite=0.1, eq=0.1)
        high = _ranked("high", composite=0.9, eq=0.9)
        cr = ClaimResult(
            claim=EvidenceClaim(
                claim_id="c", angle_id="value_precedent",
                claim_text="t", search_query="q",
            ),
            papers=[high, low],
            claim_relevance_scores={"low": 1.0, "high": 0.0},
        )
        packages = _group_into_packages(angles, [cr])
        # low: 0.5*1.0 + 0.3*0.1 + 0.2*0.1 = 0.5 + 0.03 + 0.02 = 0.55
        # high: 0.5*0.0 + 0.3*0.9 + 0.2*0.9 = 0 + 0.27 + 0.18 = 0.45
        assert packages[0].claims[0].papers[0].pmid == "low"


# ---------------------------------------------------------------------------
# TestMean
# ---------------------------------------------------------------------------

class TestMean:
    def test_empty(self):
        assert _mean([]) == 0.0

    def test_single(self):
        assert _mean([0.6]) == pytest.approx(0.6)

    def test_multiple(self):
        assert _mean([0.2, 0.4, 0.6]) == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# TestOrchestrator (end-to-end, all LLM + search mocked)
# ---------------------------------------------------------------------------

class TestOrchestrator:
    """End-to-end test with mocked LLM and search pipeline."""

    def _make_request(self) -> InterpretRequest:
        return InterpretRequest(
            finding=_finding(),
            max_results_per_angle=2,
            pool_size=5,
        )

    def _make_pool_result(self):
        from app.services.pool import PoolResult
        papers = [_paper("1", "IOP after cataract surgery"), _paper("2", "Postop pressure")]
        return PoolResult(papers=papers, source_counts={"PubMed": 2})

    @pytest.mark.asyncio
    async def test_returns_interpret_response(self):
        from app.services.pool import PoolResult

        pool = PoolResult(papers=[_paper("1")], source_counts={"PubMed": 1})
        ranked = [_ranked("1")]

        with (
            patch("app.services.interpret.search_all_sources", new_callable=AsyncMock, return_value=pool),
            patch("app.services.interpret.triage_papers", new_callable=AsyncMock, return_value=["1"]),
            patch("app.services.interpret.extract_paper", new_callable=AsyncMock, return_value=_extraction("1")),
            patch("app.services.interpret.llm_relevance_raw", new_callable=AsyncMock, return_value=0.5),
            patch("app.services.interpret.merge_relevance_llm", return_value=(0.5, {})),
            patch("app.services.interpret.normalize_extraction", return_value=MagicMock()),
            patch("app.services.interpret.rank_papers", new_callable=AsyncMock, return_value=ranked),
        ):
            req = self._make_request()
            result = await interpret_finding(req)

        assert isinstance(result, InterpretResponse)
        assert result.finding.metric_name == "IOP"
        assert len(result.angles) == 3  # placeholder returns 3 angles

    @pytest.mark.asyncio
    async def test_empty_pool_returns_empty_packages(self):
        from app.services.pool import PoolResult

        empty_pool = PoolResult(papers=[], source_counts={})
        with patch("app.services.interpret.search_all_sources", new_callable=AsyncMock, return_value=empty_pool):
            req = self._make_request()
            result = await interpret_finding(req)

        assert isinstance(result, InterpretResponse)
        # Each claim gets empty ClaimResult; 3 angles * their claims = packages, all with 0 papers
        for pkg in result.angles:
            for cr in pkg.claims:
                assert cr.papers == []

    @pytest.mark.asyncio
    async def test_claim_search_failure_does_not_crash(self):
        with patch(
            "app.services.interpret._run_claim_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ):
            # _generate_angles is still the placeholder; _run_claim_search raises
            req = self._make_request()
            result = await interpret_finding(req)

        assert isinstance(result, InterpretResponse)
        # All claim results should be empty fallbacks
        for pkg in result.angles:
            for cr in pkg.claims:
                assert cr.papers == []


# ---------------------------------------------------------------------------
# TestApiEndpoint
# ---------------------------------------------------------------------------

class TestApiEndpoint:
    def test_post_interpret_returns_200(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.pool import PoolResult

        pool = PoolResult(papers=[_paper("1")], source_counts={"PubMed": 1})
        ranked = [_ranked("1")]

        with (
            patch("app.services.interpret.search_all_sources", new_callable=AsyncMock, return_value=pool),
            patch("app.services.interpret.triage_papers", new_callable=AsyncMock, return_value=["1"]),
            patch("app.services.interpret.extract_paper", new_callable=AsyncMock, return_value=_extraction("1")),
            patch("app.services.interpret.llm_relevance_raw", new_callable=AsyncMock, return_value=0.5),
            patch("app.services.interpret.merge_relevance_llm", return_value=(0.5, {})),
            patch("app.services.interpret.normalize_extraction", return_value=MagicMock()),
            patch("app.services.interpret.rank_papers", new_callable=AsyncMock, return_value=ranked),
        ):
            client = TestClient(app)
            payload = {
                "finding": {
                    "metric_name": "IOP",
                    "metric_unit": "mmHg",
                    "observed_value": 20.0,
                    "timepoint": "POD1",
                    "procedure": "phacoemulsification",
                },
                "max_results_per_angle": 2,
                "pool_size": 5,
            }
            resp = client.post("/api/v1/interpret", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert "angles" in data
        assert "finding" in data
        assert data["finding"]["metric_name"] == "IOP"

    def test_post_interpret_invalid_payload_returns_422(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.post("/api/v1/interpret", json={"finding": {}})
        assert resp.status_code == 422
