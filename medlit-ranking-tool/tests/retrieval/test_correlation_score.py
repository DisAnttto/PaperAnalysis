"""Tests for correlation_score and its 11 feature functions."""

from __future__ import annotations

from app.retrieval.enums import SourceType
from app.retrieval.graph import EvidenceGraph
from app.retrieval.models import EvidenceRecord, ExtractedTargetProfile
from app.retrieval.scoring import (
    FEATURE_WEIGHTS,
    _endpoint_overlap,
    _exact_id_match,
    _intended_use_indication_match,
    _numeric_threshold_proximity,
    _route_delivery_match,
    _same_product_identity,
    _technology_material_match,
    _citation_linkage,
    _regulatory_linkage,
    _safety_signal_overlap,
    correlation_score,
)


def _rec(identifier: str, **kwargs) -> EvidenceRecord:
    defaults = dict(source_type=SourceType.pubmed_paper, source_name="test")
    defaults.update(kwargs)
    return EvidenceRecord(identifier=identifier, **defaults)


def _profile(**kwargs) -> ExtractedTargetProfile:
    defaults = dict(product_type="drug")
    defaults.update(kwargs)
    return ExtractedTargetProfile(**defaults)


# ── Feature 1: exact_id_match ───────────────────────────────────────────

def test_exact_id_match_same() -> None:
    r = _rec("PMID:001")
    assert _exact_id_match(r, r) == 1.0


def test_exact_id_match_different() -> None:
    assert _exact_id_match(_rec("PMID:001"), _rec("PMID:002")) == 0.0


# ── Feature 2: same_product_identity ─────────────────────────────────────

def test_product_identity_exact_match() -> None:
    p = _profile(product_name="VABYSMO", route="intravitreal")
    c = _rec("C1", product_name="VABYSMO", route="intravitreal")
    assert _same_product_identity(p, c) == 1.0


def test_product_identity_name_only() -> None:
    p = _profile(product_name="VABYSMO", route="intravitreal")
    c = _rec("C1", product_name="VABYSMO", route="oral")
    assert _same_product_identity(p, c) == 0.7


def test_product_identity_partial_overlap() -> None:
    p = _profile(product_name="VABYSMO (faricimab)")
    c = _rec("C1", product_name="faricimab injection")
    score = _same_product_identity(p, c)
    assert score >= 0.3


def test_product_identity_no_match() -> None:
    p = _profile(product_name="VABYSMO")
    c = _rec("C1", product_name="Aspirin")
    assert _same_product_identity(p, c) == 0.0


# ── Feature 4: intended_use_indication_match ─────────────────────────────

def test_indication_full_overlap() -> None:
    p = _profile(indication=["AMD", "DME"])
    c = _rec("C1", indication=["AMD", "DME"])
    assert _intended_use_indication_match(p, c) == 1.0


def test_indication_partial_overlap() -> None:
    p = _profile(indication=["AMD", "DME"])
    c = _rec("C1", indication=["AMD"])
    score = _intended_use_indication_match(p, c)
    assert 0.0 < score < 1.0


def test_indication_no_overlap() -> None:
    p = _profile(indication=["AMD"])
    c = _rec("C1", indication=["diabetes"])
    assert _intended_use_indication_match(p, c) == 0.0


# ── Feature 6: route_delivery_match ──────────────────────────────────────

def test_route_exact_match() -> None:
    p = _profile(route="intravitreal")
    c = _rec("C1", route="intravitreal")
    assert _route_delivery_match(p, c) == 1.0


def test_route_same_group() -> None:
    p = _profile(route="intravitreal")
    c = _rec("C1", route="intravenous")
    assert _route_delivery_match(p, c) == 0.5


def test_route_mismatch() -> None:
    p = _profile(route="intravitreal")
    c = _rec("C1", route="oral")
    assert _route_delivery_match(p, c) == 0.0


# ── Feature 7: endpoint_overlap (synonym expansion) ─────────────────────

def test_endpoint_synonym_match() -> None:
    p = _profile(key_metrics_or_endpoints=["BCVA", "OCT thickness"])
    c = _rec("C1", endpoints=["best corrected visual acuity", "optical coherence tomography"])
    score = _endpoint_overlap(p, c)
    assert score > 0.3


def test_endpoint_no_overlap() -> None:
    p = _profile(key_metrics_or_endpoints=["BCVA"])
    c = _rec("C1", endpoints=["blood pressure"])
    assert _endpoint_overlap(p, c) == 0.0


# ── Feature 8: numeric_threshold_proximity ───────────────────────────────

def test_numeric_threshold_close() -> None:
    p = _profile(key_thresholds=["BCVA gain >= 15 letters"])
    c = _rec("C1", endpoints=["14 letters gained"])
    score = _numeric_threshold_proximity(p, c)
    assert score > 0.5


def test_numeric_threshold_no_numbers() -> None:
    p = _profile(key_thresholds=["qualitative improvement"])
    c = _rec("C1", endpoints=["no numbers here"])
    assert _numeric_threshold_proximity(p, c) == 0.0


# ── Feature 9: citation_linkage ──────────────────────────────────────────

def test_citation_linkage_present() -> None:
    g = EvidenceGraph()
    seed = _rec("PMID:001")
    cand = _rec("PMID:002")
    g.add_node(seed)
    g.add_node(cand)
    g.add_edge("PMID:001", "PMID:002", "cited_by", 0.7)
    assert _citation_linkage(seed, cand, g) == 1.0


def test_citation_linkage_absent() -> None:
    g = EvidenceGraph()
    seed = _rec("PMID:001")
    cand = _rec("PMID:002")
    g.add_node(seed)
    g.add_node(cand)
    assert _citation_linkage(seed, cand, g) == 0.0


# ── Feature 10: regulatory_linkage ──────────────────────────────────────

def test_regulatory_linkage_present() -> None:
    g = EvidenceGraph()
    seed = _rec("PMID:001")
    cand = _rec("FDA_REVIEW:001", source_type=SourceType.fda_review)
    g.add_node(seed)
    g.add_node(cand)
    g.add_edge("FDA_REVIEW:001", "PMID:001", "review_for", 1.0)
    assert _regulatory_linkage(seed, cand, g) == 1.0


def test_regulatory_linkage_absent() -> None:
    g = EvidenceGraph()
    assert _regulatory_linkage(_rec("A"), _rec("B"), g) == 0.0


# ── Feature 11: safety_signal_overlap ────────────────────────────────────

def test_safety_signal_overlap_via_edge() -> None:
    g = EvidenceGraph()
    seed = _rec("PMID:001", product_name="DrugX")
    cand = _rec("MAUDE:001", source_type=SourceType.maude_event, product_name="DrugX")
    g.add_node(seed)
    g.add_node(cand)
    g.add_edge("MAUDE:001", "PMID:001", "safety_signal_for", 0.5)
    assert _safety_signal_overlap(seed, cand, g) == 1.0


# ── Full correlation_score ──────────────────────────────────────────────

def test_exact_id_override_returns_1() -> None:
    seed = _rec("PMID:001")
    score, features = correlation_score(seed, seed)
    assert score == 1.0
    assert features["exact_id_match"] == 1.0


def test_regulatory_linkage_floor_075() -> None:
    g = EvidenceGraph()
    seed = _rec("PMID:001")
    cand = _rec("FDA_REVIEW:001", source_type=SourceType.fda_review)
    g.add_node(seed)
    g.add_node(cand)
    g.add_edge("FDA_REVIEW:001", "PMID:001", "review_for", 1.0)
    p = _profile()
    score, features = correlation_score(seed, cand, p, g)
    assert features["regulatory_linkage"] == 1.0
    assert score >= 0.75


def test_weighted_sum_in_range() -> None:
    seed = _rec("PMID:001", product_name="X", indication=["AMD"], route="intravitreal")
    cand = _rec("PMID:002", product_name="Y", indication=["DME"], route="oral")
    p = _profile(product_name="X", indication=["AMD"], route="intravitreal")
    score, _ = correlation_score(seed, cand, p)
    assert 0.0 <= score <= 1.0


def test_feature_weights_sum_to_1() -> None:
    total = sum(FEATURE_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001
