"""Tests for app.ranking.evidence_quality (ranking_spec §2.4)."""

import pytest

from app.models.extraction import (
    ComparatorType,
    EvidenceDomainType,
    EvidenceInt,
    EvidenceStudyType,
    StudyExtraction,
)
from app.ranking.evidence_quality import STUDY_DESIGN_SCORES, score_evidence_quality


def _study(
    study_type: str = "rct",
    domain: str = "human_clinical",
    sample_size: int | None = 100,
    follow_up_months: int | None = None,
    comparator_type: ComparatorType | None = None,
) -> StudyExtraction:
    fu = None
    if follow_up_months is not None:
        fu = EvidenceInt(
            value=follow_up_months,
            evidence_snippet=str(follow_up_months),
            evidence_section="abstract",
        )
    return StudyExtraction(
        study_type=EvidenceStudyType(
            value=study_type, evidence_snippet="text",
            evidence_section="abstract",
        ),
        evidence_domain=EvidenceDomainType(
            value=domain, evidence_snippet="text",
            evidence_section="abstract",
        ),
        sample_size=(
            EvidenceInt(
                value=sample_size, evidence_snippet=str(sample_size),
                evidence_section="abstract",
            )
            if sample_size is not None
            else None
        ),
        follow_up_months=fu,
        comparator_type=comparator_type,
    )


class TestStudyDesignScores:
    @pytest.mark.parametrize(
        "study_type,expected_base",
        [
            ("systematic_review", 1.00),
            ("meta_analysis", 1.00),
            ("rct", 0.90),
            ("prospective_cohort", 0.70),
            ("retrospective_cohort", 0.50),
            ("case_control", 0.40),
            ("case_series", 0.30),
            ("case_report", 0.15),
            ("bench_study", 0.15),
            ("in_vitro_study", 0.15),
            ("animal_study", 0.20),
            ("narrative_review", 0.15),
            ("unknown", 0.20),
        ],
    )
    def test_lookup_table_values(
        self, study_type: str, expected_base: float,
    ) -> None:
        assert STUDY_DESIGN_SCORES[study_type] == expected_base


class TestSampleSizeModifier:
    def test_pivotal_scale_adds_010(self) -> None:
        score, bd = score_evidence_quality(_study(sample_size=1500))
        assert bd["size_modifier"] == 0.10
        assert abs(score - 1.0) < 1e-9

    def test_medium_sample_adds_005(self) -> None:
        score, bd = score_evidence_quality(_study(sample_size=200))
        assert bd["size_modifier"] == 0.05
        assert abs(score - 0.95) < 1e-9

    def test_small_sample_adds_002(self) -> None:
        score, bd = score_evidence_quality(_study(sample_size=50))
        assert bd["size_modifier"] == 0.02
        assert abs(score - 0.92) < 1e-9

    def test_tiny_sample_subtracts_005(self) -> None:
        score, bd = score_evidence_quality(_study(sample_size=5))
        assert bd["size_modifier"] == -0.05
        assert abs(score - 0.85) < 1e-9

    def test_missing_sample_size_no_modifier(self) -> None:
        score, bd = score_evidence_quality(_study(sample_size=None))
        assert bd["size_modifier"] == 0.00
        assert bd["sample_size"] is None
        assert abs(score - 0.90) < 1e-9

    def test_score_capped_at_one(self) -> None:
        score, _ = score_evidence_quality(
            _study(study_type="systematic_review", sample_size=5000),
        )
        assert score == 1.0


class TestFollowUpModifier:
    def test_ge_24_months_adds_008(self) -> None:
        _, bd = score_evidence_quality(
            _study(follow_up_months=30, sample_size=100),
        )
        assert bd["follow_up_modifier"] == 0.08

    def test_ge_12_months_adds_005(self) -> None:
        _, bd = score_evidence_quality(
            _study(follow_up_months=18, sample_size=100),
        )
        assert bd["follow_up_modifier"] == 0.05

    def test_ge_6_months_adds_002(self) -> None:
        _, bd = score_evidence_quality(
            _study(follow_up_months=8, sample_size=100),
        )
        assert bd["follow_up_modifier"] == 0.02

    def test_lt_6_months_zero(self) -> None:
        _, bd = score_evidence_quality(
            _study(follow_up_months=3, sample_size=100),
        )
        assert bd["follow_up_modifier"] == 0.0


class TestComparatorModifier:
    def test_active_adds_005(self) -> None:
        _, bd = score_evidence_quality(
            _study(comparator_type=ComparatorType.ACTIVE),
        )
        assert bd["comparator_modifier"] == 0.05

    def test_sham_placebo_adds_003(self) -> None:
        _, bd = score_evidence_quality(
            _study(comparator_type=ComparatorType.SHAM),
        )
        assert bd["comparator_modifier"] == 0.03
        _, bd2 = score_evidence_quality(
            _study(comparator_type=ComparatorType.PLACEBO),
        )
        assert bd2["comparator_modifier"] == 0.03

    def test_historical_adds_001(self) -> None:
        _, bd = score_evidence_quality(
            _study(comparator_type=ComparatorType.HISTORICAL),
        )
        assert bd["comparator_modifier"] == 0.01

    def test_none_unknown_zero(self) -> None:
        _, bd = score_evidence_quality(_study(comparator_type=None))
        assert bd["comparator_modifier"] == 0.0
        _, bd2 = score_evidence_quality(
            _study(comparator_type=ComparatorType.NONE),
        )
        assert bd2["comparator_modifier"] == 0.0


class TestDomainCap:
    def test_human_clinical_no_cap(self) -> None:
        score, bd = score_evidence_quality(
            _study(domain="human_clinical", sample_size=1500),
        )
        assert bd["cap_applied"] is False
        assert abs(score - 1.0) < 1e-9

    def test_animal_capped_at_060(self) -> None:
        score, bd = score_evidence_quality(
            _study(study_type="rct", domain="animal", sample_size=1500),
        )
        assert bd["cap_applied"] is True
        assert score == 0.60

    def test_in_vitro_capped_at_040(self) -> None:
        score, bd = score_evidence_quality(
            _study(study_type="rct", domain="in_vitro", sample_size=1500),
        )
        assert score == 0.40

    def test_bench_capped_at_040(self) -> None:
        score, bd = score_evidence_quality(
            _study(study_type="prospective_cohort", domain="bench", sample_size=500),
        )
        assert score == 0.40

    def test_mixed_capped_at_050(self) -> None:
        score, bd = score_evidence_quality(
            _study(study_type="rct", domain="mixed", sample_size=500),
        )
        assert score == 0.50

    def test_unknown_domain_no_cap(self) -> None:
        score, bd = score_evidence_quality(
            _study(domain="unknown", sample_size=500),
        )
        assert bd["cap_applied"] is False

    def test_cap_not_applied_when_score_below(self) -> None:
        score, bd = score_evidence_quality(
            _study(study_type="case_report", domain="animal", sample_size=5),
        )
        assert bd["cap_applied"] is False
        assert abs(score - 0.10) < 1e-9


class TestEstimatedFlag:
    def test_unknown_type_and_no_sample_flags_estimated(self) -> None:
        _, bd = score_evidence_quality(
            _study(study_type="unknown", sample_size=None),
        )
        assert bd["evidence_score_estimated"] is True

    def test_unknown_type_with_sample_not_estimated(self) -> None:
        _, bd = score_evidence_quality(
            _study(study_type="unknown", sample_size=50),
        )
        assert bd["evidence_score_estimated"] is False

    def test_known_type_without_sample_not_estimated(self) -> None:
        _, bd = score_evidence_quality(
            _study(study_type="rct", sample_size=None),
        )
        assert bd["evidence_score_estimated"] is False


class TestDeterminism:
    def test_repeated_calls_identical(self) -> None:
        study = _study(study_type="rct", sample_size=500)
        results = [score_evidence_quality(study) for _ in range(5)]
        assert all(r[0] == results[0][0] for r in results)
