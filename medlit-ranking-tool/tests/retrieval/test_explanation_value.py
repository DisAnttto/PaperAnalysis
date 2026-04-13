"""Tests for explanation_value_score in app/retrieval/scoring.py."""

from __future__ import annotations

import pytest

from app.retrieval.enums import SourceType
from app.retrieval.models import EvidenceRecord, ExtractedTargetProfile
from app.retrieval.scoring import explanation_value_score


def _rec(identifier: str = "TEST:001", **kwargs) -> EvidenceRecord:
    defaults = dict(source_type=SourceType.pubmed_paper, source_name="test")
    defaults.update(kwargs)
    return EvidenceRecord(identifier=identifier, **defaults)


def _profile(**kwargs) -> ExtractedTargetProfile:
    defaults = dict(product_type="drug")
    defaults.update(kwargs)
    return ExtractedTargetProfile(**defaults)


def test_formula_with_full_coverage() -> None:
    """All claims matched => claim_coverage=1.0 => expl = corr * str * 1.0."""
    prof = _profile(
        indication=["AMD"],
        key_metrics_or_endpoints=["BCVA"],
    )
    cand = _rec(indication=["AMD"], endpoints=["BCVA"])
    # corr=0.8, strength=0.9
    expl = explanation_value_score(prof, cand, 0.8, 0.9)
    expected = 0.8 * 0.9 * (0.4 + 0.6 * 1.0)
    assert abs(expl - expected) < 0.01


def test_formula_with_zero_coverage() -> None:
    """No claims matched => claim_coverage=0.0 => expl = corr * str * 0.4."""
    prof = _profile(
        indication=["AMD"],
        key_metrics_or_endpoints=["BCVA"],
    )
    cand = _rec(indication=["diabetes"], endpoints=["blood pressure"])
    expl = explanation_value_score(prof, cand, 0.8, 0.9)
    expected = 0.8 * 0.9 * 0.4
    assert abs(expl - expected) < 0.01


def test_formula_with_partial_coverage() -> None:
    """Half claims matched => claim_coverage=0.5."""
    prof = _profile(
        indication=["AMD", "DME"],
        key_metrics_or_endpoints=["BCVA", "IOP"],
    )
    # Only 2 of 4 claims will match
    cand = _rec(indication=["AMD"], endpoints=["BCVA"])
    expl = explanation_value_score(prof, cand, 0.8, 0.9)
    coverage = 2 / 4
    expected = 0.8 * 0.9 * (0.4 + 0.6 * coverage)
    assert abs(expl - expected) < 0.05


def test_no_claims_returns_base_factor() -> None:
    """Profile with no claims => expl = corr * str * 0.4."""
    prof = _profile(indication=[], key_metrics_or_endpoints=[], key_thresholds=[])
    cand = _rec()
    expl = explanation_value_score(prof, cand, 0.8, 0.9)
    expected = 0.8 * 0.9 * 0.4
    assert abs(expl - expected) < 0.01


def test_synonym_endpoint_matched() -> None:
    """'BCVA' in profile should match 'best corrected visual acuity' in candidate."""
    prof = _profile(
        indication=["AMD"],
        key_metrics_or_endpoints=["BCVA"],
    )
    cand = _rec(indication=["AMD"], endpoints=["best corrected visual acuity"])
    expl = explanation_value_score(prof, cand, 0.8, 0.9)
    # Both claims should match
    expected = 0.8 * 0.9 * (0.4 + 0.6 * 1.0)
    assert abs(expl - expected) < 0.01


def test_score_always_in_range() -> None:
    prof = _profile(
        indication=["AMD", "DME"],
        key_metrics_or_endpoints=["BCVA", "OCT thickness", "dosing interval durability"],
    )
    cand = _rec(
        indication=["AMD", "DME"],
        endpoints=["BCVA", "OCT thickness"],
    )
    expl = explanation_value_score(prof, cand, 1.0, 1.0)
    assert 0.0 <= expl <= 1.0


def test_zero_scores_return_zero() -> None:
    prof = _profile(indication=["AMD"], key_metrics_or_endpoints=["BCVA"])
    cand = _rec(indication=["AMD"], endpoints=["BCVA"])
    assert explanation_value_score(prof, cand, 0.0, 0.0) == 0.0
