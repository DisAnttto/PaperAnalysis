"""Tests for the evidence graph model (app/retrieval/graph.py)."""

from __future__ import annotations

from app.retrieval.enums import SourceType, TierLevel
from app.retrieval.graph import EvidenceGraph, build_evidence_graph
from app.retrieval.models import EvidenceRecord


def _rec(identifier: str, **kwargs) -> EvidenceRecord:
    defaults = dict(source_type=SourceType.pubmed_paper, source_name="test")
    defaults.update(kwargs)
    return EvidenceRecord(identifier=identifier, **defaults)


def _build_small_graph() -> EvidenceGraph:
    """5 nodes, 8 edges mirroring a small regulatory subgraph."""
    g = EvidenceGraph()
    seed = _rec("PMID:001")
    review = _rec("FDA_REVIEW:001", source_type=SourceType.fda_review)
    label = _rec("LABEL:001", source_type=SourceType.fda_label)
    trial = _rec("NCT:001", source_type=SourceType.clinicaltrials)
    distant = _rec("PMID:999")

    for r in (seed, review, label, trial, distant):
        g.add_node(r)

    g.add_edge("FDA_REVIEW:001", "PMID:001", "review_for", 1.0, "FDA review")
    g.add_edge("LABEL:001", "PMID:001", "label_for", 0.95, "label link")
    g.add_edge("NCT:001", "PMID:001", "trial_for", 0.9, "trial link")
    g.add_edge("PMID:001", "LABEL:001", "same_product", 0.6, "shared product")
    g.add_edge("PMID:001", "NCT:001", "same_indication", 0.5, "shared indication")
    g.add_edge("NCT:001", "LABEL:001", "same_endpoint", 0.4, "shared endpoint")
    g.add_edge("PMID:001", "PMID:999", "same_indication", 0.5, "distant indication")
    g.add_edge("PMID:999", "NCT:001", "same_endpoint", 0.4, "distant endpoint")

    return g


# ── Basic graph operations ───────────────────────────────────────────────

def test_add_node_and_count() -> None:
    g = EvidenceGraph()
    g.add_node(_rec("A"))
    g.add_node(_rec("B"))
    assert len(g.nodes) == 2


def test_add_edge_auto_creates_nodes() -> None:
    g = EvidenceGraph()
    g.add_edge("X", "Y", "same_product", 0.6)
    assert "X" in g.nodes
    assert "Y" in g.nodes


def test_get_neighbors_out() -> None:
    g = _build_small_graph()
    nbrs = g.get_neighbors("PMID:001", direction="out")
    ids = {n.identifier for n, _ in nbrs}
    assert "LABEL:001" in ids
    assert "PMID:999" in ids


def test_get_neighbors_filtered_by_edge_type() -> None:
    g = _build_small_graph()
    nbrs = g.get_neighbors("PMID:001", edge_types=["same_product"], direction="both")
    ids = {n.identifier for n, _ in nbrs}
    assert "LABEL:001" in ids


# ── Path / distance ─────────────────────────────────────────────────────

def test_shortest_path_self() -> None:
    g = _build_small_graph()
    assert g.shortest_path("PMID:001", "PMID:001") == ["PMID:001"]


def test_shortest_path_direct() -> None:
    g = _build_small_graph()
    path = g.shortest_path("PMID:001", "FDA_REVIEW:001")
    assert path is not None
    assert len(path) == 2


def test_shortest_path_two_hops() -> None:
    g = _build_small_graph()
    path = g.shortest_path("FDA_REVIEW:001", "LABEL:001")
    assert path is not None
    assert len(path) <= 3


def test_hop_distance_self() -> None:
    g = _build_small_graph()
    assert g.hop_distance("PMID:001", "PMID:001") == 0


def test_hop_distance_direct() -> None:
    g = _build_small_graph()
    assert g.hop_distance("PMID:001", "FDA_REVIEW:001") == 1


def test_hop_distance_unreachable() -> None:
    g = EvidenceGraph()
    g.add_node(_rec("A"))
    g.add_node(_rec("B"))
    assert g.hop_distance("A", "B") is None


# ── Subgraph ─────────────────────────────────────────────────────────────

def test_subgraph_max_hops_1() -> None:
    g = _build_small_graph()
    sg = g.subgraph("PMID:001", max_hops=1)
    assert "PMID:001" in sg.nodes
    assert "FDA_REVIEW:001" in sg.nodes
    assert len(sg.nodes) >= 3


def test_subgraph_max_hops_0() -> None:
    g = _build_small_graph()
    sg = g.subgraph("PMID:001", max_hops=0)
    assert len(sg.nodes) == 1


# ── Tier inference ───────────────────────────────────────────────────────

def test_tier0_self() -> None:
    g = _build_small_graph()
    assert g.infer_tier("PMID:001", "PMID:001") == TierLevel.Tier0


def test_tier1_review_edge() -> None:
    g = _build_small_graph()
    tier = g.infer_tier("PMID:001", "FDA_REVIEW:001")
    assert tier == TierLevel.Tier1


def test_tier1_label_edge() -> None:
    g = _build_small_graph()
    tier = g.infer_tier("PMID:001", "LABEL:001")
    assert tier in (TierLevel.Tier1, TierLevel.Tier2)


def test_tier_distant_node() -> None:
    g = _build_small_graph()
    tier = g.infer_tier("PMID:001", "PMID:999")
    assert tier in (TierLevel.Tier2, TierLevel.Tier3, TierLevel.Tier4)


def test_tier5_unreachable() -> None:
    g = EvidenceGraph()
    g.add_node(_rec("A"))
    g.add_node(_rec("B"))
    assert g.infer_tier("A", "B") == TierLevel.Tier5


# ── build_evidence_graph ────────────────────────────────────────────────

def test_build_graph_creates_product_edges() -> None:
    seed = _rec("PMID:001", product_name="TestDrug", indication=["AMD"])
    cand = _rec("PMID:002", product_name="TestDrug", indication=["AMD"])
    g = build_evidence_graph(seed, [cand])
    assert len(g.edges) >= 1
    edge_types = {e.edge_type for e in g.edges}
    assert "same_product" in edge_types or "same_indication" in edge_types
