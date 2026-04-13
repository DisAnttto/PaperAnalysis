"""Tests for app.ranking.metric_favorability (ranking_spec §2.3)."""

import pytest

from app.models.extraction import ExtractedMetric
from app.models.search import TargetMetric
from app.ranking.metric_favorability import score_metric_favorability


def _metric(name: str, value: float, vtype: str = "numeric") -> ExtractedMetric:
    return ExtractedMetric(
        metric_name_normalized=name,
        metric_name_raw=name,
        metric_category="safety",
        value_type=vtype,
        numeric_value=value,
        unit="%" if vtype == "percentage" else None,
        evidence_snippet=f"{name} = {value}",
        evidence_section="abstract",
    )


def _range_metric(name: str, lo: float, hi: float) -> ExtractedMetric:
    return ExtractedMetric(
        metric_name_normalized=name,
        metric_name_raw=name,
        metric_category="efficacy",
        value_type="range",
        value_min=lo,
        value_max=hi,
        evidence_snippet=f"{name} = {lo}-{hi}",
        evidence_section="abstract",
    )


class TestDirectionModes:
    def test_higher_better_above_threshold(self) -> None:
        extracted = [_metric("score", 8.0)]
        targets = [TargetMetric(
            metric_name_normalized="score",
            direction="higher_better",
            threshold=5.0,
            normalisation_range=10.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert abs(score - 0.3) < 1e-9

    def test_higher_better_below_threshold(self) -> None:
        extracted = [_metric("score", 3.0)]
        targets = [TargetMetric(
            metric_name_normalized="score",
            direction="higher_better",
            threshold=5.0,
            normalisation_range=10.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert score == 0.0

    def test_lower_better_well_below(self) -> None:
        extracted = [_metric("mace_rate", 2.0)]
        targets = [TargetMetric(
            metric_name_normalized="mace_rate",
            direction="lower_better",
            threshold=10.0,
            normalisation_range=10.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert abs(score - 0.8) < 1e-9

    def test_lower_better_above_threshold(self) -> None:
        extracted = [_metric("mace_rate", 15.0)]
        targets = [TargetMetric(
            metric_name_normalized="mace_rate",
            direction="lower_better",
            threshold=10.0,
            normalisation_range=10.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert score == 0.0

    def test_range_best_inside_range(self) -> None:
        extracted = [_metric("bp", 120.0)]
        targets = [TargetMetric(
            metric_name_normalized="bp",
            direction="range_best",
            range_lo=90.0,
            range_hi=140.0,
            normalisation_range=100.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert score == 1.0

    def test_range_best_outside_range(self) -> None:
        extracted = [_metric("bp", 160.0)]
        targets = [TargetMetric(
            metric_name_normalized="bp",
            direction="range_best",
            range_lo=90.0,
            range_hi=140.0,
            normalisation_range=100.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert 0.0 < score < 1.0

    def test_closer_better_exact_match(self) -> None:
        extracted = [_metric("temp", 37.0)]
        targets = [TargetMetric(
            metric_name_normalized="temp",
            direction="closer_better",
            target=37.0,
            normalisation_range=5.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert score == 1.0

    def test_closer_better_offset(self) -> None:
        extracted = [_metric("temp", 39.0)]
        targets = [TargetMetric(
            metric_name_normalized="temp",
            direction="closer_better",
            target=37.0,
            normalisation_range=5.0,
        )]
        score, _ = score_metric_favorability(extracted, targets)
        assert abs(score - 0.6) < 1e-9


class TestMissingMetrics:
    def test_no_target_metrics_marks_excluded(self) -> None:
        score, bd = score_metric_favorability([], [])
        assert score == 0.0
        assert bd["excluded"] is True

    def test_target_present_but_no_match_flags_incomplete(self) -> None:
        extracted = [_metric("other_metric", 5.0)]
        targets = [TargetMetric(
            metric_name_normalized="mace_rate",
            direction="lower_better",
            threshold=10.0,
            normalisation_range=10.0,
        )]
        score, bd = score_metric_favorability(extracted, targets)
        assert score == 0.0
        assert bd["metric_score_incomplete"] is True
        assert bd["metric_score_estimated"] is False

    def test_partial_match_flags_estimated(self) -> None:
        extracted = [_metric("mace_rate", 4.0)]
        targets = [
            TargetMetric(
                metric_name_normalized="mace_rate",
                direction="lower_better",
                threshold=10.0,
                normalisation_range=10.0,
            ),
            TargetMetric(
                metric_name_normalized="tlr_rate",
                direction="lower_better",
                threshold=5.0,
                normalisation_range=5.0,
            ),
        ]
        score, bd = score_metric_favorability(extracted, targets)
        assert score > 0.0
        assert bd["metric_score_estimated"] is True
        assert bd["metric_score_incomplete"] is False
        assert "tlr_rate" in bd["unmatched"]

    def test_all_targets_matched(self) -> None:
        extracted = [_metric("mace_rate", 4.0), _metric("tlr_rate", 2.0)]
        targets = [
            TargetMetric(
                metric_name_normalized="mace_rate",
                direction="lower_better",
                threshold=10.0,
                normalisation_range=10.0,
            ),
            TargetMetric(
                metric_name_normalized="tlr_rate",
                direction="lower_better",
                threshold=5.0,
                normalisation_range=5.0,
            ),
        ]
        _, bd = score_metric_favorability(extracted, targets)
        assert bd["metric_score_estimated"] is False
        assert bd["metric_score_incomplete"] is False


class TestRangeMetricMidpoint:
    def test_range_type_uses_midpoint(self) -> None:
        extracted = [_range_metric("ci", 2.0, 6.0)]
        targets = [TargetMetric(
            metric_name_normalized="ci",
            direction="lower_better",
            threshold=10.0,
            normalisation_range=10.0,
        )]
        score, bd = score_metric_favorability(extracted, targets)
        assert abs(score - 0.6) < 1e-9


class TestCoverageFallbackAliases:
    def test_cst_matches_central_subfield_thickness(self) -> None:
        extracted = [
            ExtractedMetric(
                metric_name_normalized="central_subfield_thickness",
                metric_name_raw="central subfield thickness (CST)",
                metric_category="efficacy",
                value_type="numeric",
                numeric_value=300.0,
                evidence_snippet="CST",
                evidence_section="abstract",
            ),
        ]
        score, bd = score_metric_favorability(
            extracted,
            [],
            metrics_of_interest=["CST", "BCVA", "macular volume"],
        )
        assert bd.get("coverage_mode") is True
        assert score >= 1.0 / 3.0
        assert "CST" in bd["matched"]

    def test_bcva_matches_best_corrected_phrase(self) -> None:
        extracted = [
            ExtractedMetric(
                metric_name_normalized="best_corrected_visual_acuity",
                metric_name_raw="best-corrected visual acuity",
                metric_category="efficacy",
                value_type="numeric",
                numeric_value=70.0,
                evidence_snippet="BCVA",
                evidence_section="abstract",
            ),
        ]
        score, bd = score_metric_favorability(
            extracted,
            [],
            metrics_of_interest=["BCVA"],
        )
        assert score == 1.0

    def test_cft_matches_central_foveal_thickness(self) -> None:
        extracted = [
            ExtractedMetric(
                metric_name_normalized="central_foveal_thickness",
                metric_name_raw="central foveal thickness (CFT)",
                metric_category="efficacy",
                value_type="numeric",
                numeric_value=320.0,
                evidence_snippet="CFT",
                evidence_section="abstract",
            ),
        ]
        score, bd = score_metric_favorability(
            extracted,
            [],
            metrics_of_interest=["CFT"],
        )
        assert bd.get("coverage_mode") is True
        assert score == 1.0
        assert "CFT" in bd["matched"]

    def test_iop_matches_intraocular_pressure(self) -> None:
        extracted = [
            ExtractedMetric(
                metric_name_normalized="intraocular_pressure",
                metric_name_raw="intraocular pressure (IOP)",
                metric_category="efficacy",
                value_type="numeric",
                numeric_value=15.0,
                evidence_snippet="IOP",
                evidence_section="abstract",
            ),
        ]
        score, bd = score_metric_favorability(
            extracted,
            [],
            metrics_of_interest=["IOP"],
        )
        assert bd.get("coverage_mode") is True
        assert score == 1.0
        assert "IOP" in bd["matched"]


class TestDeterminism:
    def test_repeated_calls_identical(self) -> None:
        extracted = [_metric("mace_rate", 4.2)]
        targets = [TargetMetric(
            metric_name_normalized="mace_rate",
            direction="lower_better",
            threshold=10.0,
            normalisation_range=10.0,
        )]
        results = [
            score_metric_favorability(extracted, targets) for _ in range(5)
        ]
        assert all(r[0] == results[0][0] for r in results)
