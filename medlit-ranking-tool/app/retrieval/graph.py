"""Evidence graph model for regulatory-evidence linkage.

Provides :class:`EvidenceGraph` -- a lightweight adjacency-list graph whose
nodes wrap :class:`EvidenceRecord` and edges encode typed regulatory
relationships (predicate, review, label, citation, overlap, ...).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.retrieval.enums import TierLevel
from app.retrieval.models import EvidenceRecord


# ── Edge types recognised by the graph ────────────────────────────────────
EDGE_TYPES = frozenset({
    "predicate_of",
    "review_for",
    "label_for",
    "trial_for",
    "cited_by",
    "same_product",
    "same_ingredient",
    "same_indication",
    "same_endpoint",
    "safety_signal_for",
})

_TIER1_EDGE_TYPES = {"predicate_of", "review_for", "label_for", "trial_for", "same_product"}


# ── Node ──────────────────────────────────────────────────────────────────
class EvidenceNode:
    """Wraps an :class:`EvidenceRecord` as a graph node, hashable by identifier."""

    def __init__(self, record: EvidenceRecord) -> None:
        self.record = record
        self.outgoing: set[str] = set()
        self.incoming: set[str] = set()

    @property
    def identifier(self) -> str:
        return self.record.identifier

    @property
    def source_type(self) -> str:
        return self.record.source_type

    def __hash__(self) -> int:
        return hash(self.identifier)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EvidenceNode):
            return NotImplemented
        return self.identifier == other.identifier

    def __repr__(self) -> str:
        return f"EvidenceNode({self.identifier!r})"


# ── Edge ──────────────────────────────────────────────────────────────────
class EvidenceEdge:
    """Typed, weighted edge between two evidence nodes."""

    def __init__(
        self,
        source_node: str,
        target_node: str,
        edge_type: str,
        strength: float = 0.0,
        provenance: str = "",
    ) -> None:
        self.source_node = source_node
        self.target_node = target_node
        self.edge_type = edge_type
        self.strength = strength
        self.provenance = provenance

    def __repr__(self) -> str:
        return (
            f"EvidenceEdge({self.source_node!r} -> {self.target_node!r}, "
            f"{self.edge_type}, s={self.strength:.2f})"
        )


# ── Graph ─────────────────────────────────────────────────────────────────
class EvidenceGraph:
    """Graph of evidence records connected by regulatory relationship edges."""

    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}
        self._edges: list[EvidenceEdge] = []
        self._adj: dict[str, list[EvidenceEdge]] = {}
        self._radj: dict[str, list[EvidenceEdge]] = {}

    # -- mutation ---------------------------------------------------------

    def add_node(self, record: EvidenceRecord) -> None:
        nid = record.identifier
        if nid in self._nodes:
            self._nodes[nid].record = record
            return
        node = EvidenceNode(record)
        self._nodes[nid] = node
        self._adj.setdefault(nid, [])
        self._radj.setdefault(nid, [])

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        strength: float = 0.0,
        provenance: str = "",
    ) -> None:
        for nid in (source_id, target_id):
            if nid not in self._nodes:
                stub = EvidenceRecord(
                    identifier=nid,
                    source_type="pubmed_paper",
                    source_name="auto",
                )
                self.add_node(stub)
        edge = EvidenceEdge(source_id, target_id, edge_type, strength, provenance)
        self._edges.append(edge)
        self._adj[source_id].append(edge)
        self._radj[target_id].append(edge)
        self._nodes[source_id].outgoing.add(target_id)
        self._nodes[target_id].incoming.add(source_id)

    # -- queries ----------------------------------------------------------

    @property
    def nodes(self) -> dict[str, EvidenceNode]:
        return self._nodes

    @property
    def edges(self) -> list[EvidenceEdge]:
        return list(self._edges)

    def get_neighbors(
        self,
        identifier: str,
        edge_types: list[str] | None = None,
        direction: str = "both",
    ) -> list[tuple[EvidenceNode, EvidenceEdge]]:
        result: list[tuple[EvidenceNode, EvidenceEdge]] = []
        if direction in ("out", "both"):
            for e in self._adj.get(identifier, []):
                if edge_types is None or e.edge_type in edge_types:
                    node = self._nodes.get(e.target_node)
                    if node:
                        result.append((node, e))
        if direction in ("in", "both"):
            for e in self._radj.get(identifier, []):
                if edge_types is None or e.edge_type in edge_types:
                    node = self._nodes.get(e.source_node)
                    if node:
                        result.append((node, e))
        return result

    def get_edges_between(self, a: str, b: str) -> list[EvidenceEdge]:
        found: list[EvidenceEdge] = []
        for e in self._adj.get(a, []):
            if e.target_node == b:
                found.append(e)
        for e in self._adj.get(b, []):
            if e.target_node == a:
                found.append(e)
        return found

    def shortest_path(self, from_id: str, to_id: str) -> list[str] | None:
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        if from_id == to_id:
            return [from_id]
        visited: set[str] = {from_id}
        queue: deque[list[str]] = deque([[from_id]])
        while queue:
            path = queue.popleft()
            current = path[-1]
            for e in self._adj.get(current, []):
                nbr = e.target_node
                if nbr not in visited:
                    new_path = path + [nbr]
                    if nbr == to_id:
                        return new_path
                    visited.add(nbr)
                    queue.append(new_path)
            for e in self._radj.get(current, []):
                nbr = e.source_node
                if nbr not in visited:
                    new_path = path + [nbr]
                    if nbr == to_id:
                        return new_path
                    visited.add(nbr)
                    queue.append(new_path)
        return None

    def hop_distance(self, from_id: str, to_id: str) -> int | None:
        path = self.shortest_path(from_id, to_id)
        if path is None:
            return None
        return len(path) - 1

    def subgraph(self, center_id: str, max_hops: int = 2) -> "EvidenceGraph":
        sg = EvidenceGraph()
        if center_id not in self._nodes:
            return sg
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(center_id, 0)])
        while queue:
            nid, depth = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = self._nodes.get(nid)
            if node:
                sg.add_node(node.record)
            if depth < max_hops:
                for e in self._adj.get(nid, []):
                    queue.append((e.target_node, depth + 1))
                for e in self._radj.get(nid, []):
                    queue.append((e.source_node, depth + 1))
        for e in self._edges:
            if e.source_node in visited and e.target_node in visited:
                sg._edges.append(e)
                sg._adj.setdefault(e.source_node, []).append(e)
                sg._radj.setdefault(e.target_node, []).append(e)
        return sg

    # -- tier inference ----------------------------------------------------

    def infer_tier(self, seed_id: str, candidate_id: str) -> TierLevel:
        if seed_id == candidate_id:
            return TierLevel.Tier0
        hops = self.hop_distance(seed_id, candidate_id)
        if hops is None:
            return TierLevel.Tier5

        if hops == 1:
            edges = self.get_edges_between(seed_id, candidate_id)
            if any(e.edge_type in _TIER1_EDGE_TYPES for e in edges):
                return TierLevel.Tier1

        if hops <= 2:
            path = self.shortest_path(seed_id, candidate_id)
            if path:
                for i in range(len(path) - 1):
                    for e in self.get_edges_between(path[i], path[i + 1]):
                        if e.strength >= 0.6:
                            return TierLevel.Tier2
            return TierLevel.Tier2

        if hops <= 3:
            return TierLevel.Tier3

        edges = self.get_edges_between(seed_id, candidate_id)
        all_edges_on_path = []
        path = self.shortest_path(seed_id, candidate_id)
        if path:
            for i in range(len(path) - 1):
                all_edges_on_path.extend(self.get_edges_between(path[i], path[i + 1]))
        if all(e.edge_type in ("same_indication", "same_endpoint") for e in all_edges_on_path):
            return TierLevel.Tier4

        return TierLevel.Tier4


# ── Graph construction from evidence records ──────────────────────────────

def _normalize(s: str | None) -> str:
    return (s or "").strip().lower()


def _token_set(s: str | None) -> set[str]:
    return {t for t in _normalize(s).split() if len(t) > 1}


def build_evidence_graph(
    seed: EvidenceRecord,
    candidates: list[EvidenceRecord],
) -> EvidenceGraph:
    """Construct an :class:`EvidenceGraph` from a seed and candidate records.

    Infers edges based on regulatory relationships found in record metadata
    (predicate fields, shared products, shared indications, shared endpoints,
    safety signal linkages).
    """
    g = EvidenceGraph()
    g.add_node(seed)
    for c in candidates:
        g.add_node(c)

    all_records = [seed] + candidates
    seed_id = seed.identifier

    for cand in candidates:
        cid = cand.identifier
        payload = cand.raw_payload or {}

        # FDA predicate links (510k predicate_device)
        predicate_k = payload.get("predicate_510k_number") or payload.get("k_number_predicate")
        if predicate_k and predicate_k in seed_id:
            g.add_edge(cid, seed_id, "predicate_of", 1.0, "openFDA 510k predicate field")

        # Review / SSED linkage
        if cand.source_type in ("fda_review", "fda_ssed"):
            if _products_match(seed, cand):
                g.add_edge(cid, seed_id, "review_for", 1.0, "FDA review/SSED for same product")

        # Label linkage
        if cand.source_type in ("fda_label", "dailymed_label"):
            if _products_match(seed, cand):
                g.add_edge(cid, seed_id, "label_for", 0.95, "label for same product")

        # Trial linkage
        if cand.source_type == "clinicaltrials":
            if _products_match(seed, cand) or _indications_overlap(seed, cand):
                g.add_edge(cid, seed_id, "trial_for", 0.9, "trial for related product/indication")

        # Same product / ingredient
        if _products_match(seed, cand):
            g.add_edge(seed_id, cid, "same_product", 0.6, "shared product name")
        elif _ingredients_match(seed, cand):
            g.add_edge(seed_id, cid, "same_ingredient", 0.6, "shared active ingredient")

        # Same indication
        if _indications_overlap(seed, cand):
            g.add_edge(seed_id, cid, "same_indication", 0.5, "shared indication")

        # Same endpoint
        if _endpoints_overlap(seed, cand):
            g.add_edge(seed_id, cid, "same_endpoint", 0.4, "shared endpoint")

        # Safety signal
        if cand.source_type in ("maude_event", "fda_recall"):
            if _products_match(seed, cand):
                g.add_edge(cid, seed_id, "safety_signal_for", 0.5, "safety signal for same product")

    # Cross-candidate edges for product overlap
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if _products_match(a, b):
                g.add_edge(a.identifier, b.identifier, "same_product", 0.6, "shared product name")

    return g


def _products_match(a: EvidenceRecord, b: EvidenceRecord) -> bool:
    na = _normalize(a.product_name)
    nb = _normalize(b.product_name)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = _token_set(a.product_name), _token_set(b.product_name)
    if ta and tb and len(ta & tb) >= min(2, min(len(ta), len(tb))):
        return True
    return False


def _ingredients_match(a: EvidenceRecord, b: EvidenceRecord) -> bool:
    pa = (a.raw_payload or {}).get("active_ingredient") or ""
    pb = (b.raw_payload or {}).get("active_ingredient") or ""
    if not pa and not pb:
        return False
    return _normalize(pa) == _normalize(pb) and bool(pa)


def _indications_overlap(a: EvidenceRecord, b: EvidenceRecord) -> bool:
    sa = {_normalize(i) for i in a.indication if i}
    sb = {_normalize(i) for i in b.indication if i}
    return bool(sa & sb)


def _endpoints_overlap(a: EvidenceRecord, b: EvidenceRecord) -> bool:
    sa = {_normalize(e) for e in a.endpoints if e}
    sb = {_normalize(e) for e in b.endpoints if e}
    return bool(sa & sb)
