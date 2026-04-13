"""Multi-stage correlated-evidence retrieval pipeline orchestrator.

Seven stages:
  1. Self-match -- resolve seed, build SeedRecord + ExtractedTargetProfile
  2. Candidate expansion -- fan out to external APIs
  3. Fusion -- deduplicate and merge
  4. Graph construction -- build evidence graph, infer edges
  5. Scoring -- correlation, strength, explanation for each candidate
  6. Ranking -- composite sort
  7. Validation -- must-retrieve warnings
"""

from __future__ import annotations

import re
import time
from typing import Any

from loguru import logger

from app.core.config import Settings, settings as _default_settings
from app.retrieval.enums import RelationLabel, SourceType, TierLevel
from app.retrieval.expansion import expand_candidates
from app.retrieval.fusion import fuse_candidates
from app.retrieval.graph import EvidenceGraph, build_evidence_graph
from app.retrieval.models import (
    CorrelationResult,
    EvidenceRecord,
    ExtractedTargetProfile,
    RetrievalResponse,
    SeedRecord,
)
from app.retrieval.scoring import (
    correlation_score,
    evidence_strength_score,
    explanation_value_score,
)

# Composite ranking weights
_W_CORR = 0.45
_W_STR = 0.30
_W_EXPL = 0.25


# ── Stage 1 helpers ──────────────────────────────────────────────────────

_PREFIX_RE = re.compile(
    r"^(?P<prefix>PMID|PMC|NCT|K|DEN|PMA|NDA|BLA)[:_]?",
    re.IGNORECASE,
)


def _seed_record_from_identifier(seed_identifier: str) -> SeedRecord:
    s = seed_identifier.strip()
    m = _PREFIX_RE.match(s)
    prefix = m.group("prefix").upper() if m else ""
    mapping: dict[str, tuple[SourceType, str]] = {
        "PMID": (SourceType.pubmed_paper, "PubMed"),
        "PMC": (SourceType.pmc_article, "PMC"),
        "NCT": (SourceType.clinicaltrials, "ClinicalTrials.gov"),
        "K": (SourceType.fda_510k, "FDA 510(k)"),
        "DEN": (SourceType.fda_denovo, "FDA De Novo"),
        "PMA": (SourceType.fda_pma, "FDA PMA"),
        "NDA": (SourceType.fda_label, "FDA NDA"),
        "BLA": (SourceType.fda_label, "FDA BLA"),
    }
    source_type, source_name = mapping.get(prefix, (SourceType.pubmed_paper, "seed"))
    return SeedRecord(
        source_type=source_type,
        source_name=source_name,
        identifier=s,
    )


def _default_profile(seed: SeedRecord) -> ExtractedTargetProfile:
    """Minimal profile when no extraction is available."""
    return ExtractedTargetProfile(product_type="unknown")


class _PubMedAdapter:
    """Wraps app.services.pubmed.search_pubmed as a client object."""

    async def search_pubmed(self, query: str) -> list[Any]:
        from app.services.pubmed import search_pubmed

        papers = await search_pubmed(query, max_results=10)
        return [p.model_dump() for p in papers]


def _build_clients(cfg: Settings) -> dict[str, Any]:
    """Instantiate API clients from settings."""
    from app.clients.accessgudid import AccessGUDIDClient
    from app.clients.clinicaltrials import ClinicalTrialsClient
    from app.clients.dailymed import DailyMedClient
    from app.clients.openfda import OpenFDAClient

    return {
        "openfda": OpenFDAClient(cfg),
        "clinicaltrials": ClinicalTrialsClient(cfg),
        "dailymed": DailyMedClient(cfg),
        "accessgudid": AccessGUDIDClient(cfg),
        "pubmed": _PubMedAdapter(),
    }


# ── Relation label inference ─────────────────────────────────────────────

_EDGE_TO_RELATION: dict[str, RelationLabel] = {
    "predicate_of": RelationLabel.direct_predicate,
    "review_for": RelationLabel.direct_review,
    "label_for": RelationLabel.label,
    "trial_for": RelationLabel.linked_trial,
    "cited_by": RelationLabel.direct_citation,
    "same_product": RelationLabel.direct_same_product,
    "same_ingredient": RelationLabel.same_ingredient,
    "same_indication": RelationLabel.same_indication,
    "same_endpoint": RelationLabel.same_endpoint,
    "safety_signal_for": RelationLabel.contextual,
}


def _infer_relation(
    seed_id: str, cand_id: str, graph: EvidenceGraph
) -> RelationLabel:
    if seed_id == cand_id:
        return RelationLabel.self_match
    edges = graph.get_edges_between(seed_id, cand_id)
    if not edges:
        return RelationLabel.contextual
    # pick strongest edge
    best = max(edges, key=lambda e: e.strength)
    return _EDGE_TO_RELATION.get(best.edge_type, RelationLabel.contextual)


# ── Main pipeline ────────────────────────────────────────────────────────

async def retrieve_correlated_evidence(
    seed_identifier: str,
    settings: Settings | None = None,
    profile_override: ExtractedTargetProfile | None = None,
) -> RetrievalResponse:
    """Run the full 7-stage retrieval pipeline for *seed_identifier*."""
    t0 = time.monotonic()
    cfg = settings or _default_settings
    warnings_list: list[str] = []

    # ── Stage 1: Self-match ──────────────────────────────────────────
    seed = _seed_record_from_identifier(seed_identifier)
    profile = profile_override or _default_profile(seed)
    logger.info(
        "Pipeline stage 1: seed={}, profile_override={}, "
        "product_name={!r}, active_ingredient={!r}, route={!r}, "
        "indication={}, endpoints={}",
        seed.identifier,
        profile_override is not None,
        profile.product_name,
        profile.active_ingredient,
        profile.route,
        profile.indication,
        profile.key_metrics_or_endpoints,
    )
    seed_evidence = EvidenceRecord(
        identifier=seed.identifier,
        source_type=seed.source_type,
        source_name=seed.source_name,
        url=seed.url,
        title=seed.title,
        product_name=profile.product_name,
        indication=list(profile.indication),
        route=profile.route,
        endpoints=list(profile.key_metrics_or_endpoints),
    )

    # ── Stage 2: Candidate expansion ─────────────────────────────────
    clients = _build_clients(cfg)
    raw_candidates = await expand_candidates(seed, profile, clients)
    logger.info("Pipeline stage 2: {} raw candidates", len(raw_candidates))

    # ── Stage 3: Fusion ──────────────────────────────────────────────
    fused = fuse_candidates(raw_candidates)
    logger.info("Pipeline stage 3: {} fused candidates", len(fused))

    # ── Stage 4: Graph construction ──────────────────────────────────
    graph = build_evidence_graph(seed_evidence, fused)
    logger.info(
        "Pipeline stage 4: graph has {} nodes, {} edges",
        len(graph.nodes),
        len(graph.edges),
    )

    # ── Stage 5: Scoring ─────────────────────────────────────────────
    results: list[CorrelationResult] = []

    # Self-match at rank 1
    self_strength = evidence_strength_score(seed_evidence)
    self_expl = explanation_value_score(profile, seed_evidence, 1.0, self_strength)
    results.append(
        CorrelationResult(
            candidate=seed_evidence,
            correlation_score=1.0,
            evidence_strength_score=self_strength,
            explanation_value_score=self_expl,
            relation_label=RelationLabel.self_match,
            tier=TierLevel.Tier0,
            matched_features={"exact_id_match": 1.0},
            rationale="Self-match: seed record itself.",
        )
    )

    for cand in fused:
        if cand.identifier == seed.identifier:
            continue
        corr, features = correlation_score(seed_evidence, cand, profile, graph)
        strength = evidence_strength_score(cand)
        expl = explanation_value_score(profile, cand, corr, strength)
        rel = _infer_relation(seed.identifier, cand.identifier, graph)
        tier = graph.infer_tier(seed.identifier, cand.identifier)

        results.append(
            CorrelationResult(
                candidate=cand,
                correlation_score=round(corr, 4),
                evidence_strength_score=round(strength, 4),
                explanation_value_score=round(expl, 4),
                relation_label=rel,
                tier=tier,
                matched_features={k: round(v, 4) for k, v in features.items()},
            )
        )

    logger.info("Pipeline stage 5: scored {} candidates", len(results) - 1)

    # ── Stage 6: Ranking ─────────────────────────────────────────────
    def _composite(r: CorrelationResult) -> float:
        return (
            _W_CORR * r.correlation_score
            + _W_STR * r.evidence_strength_score
            + _W_EXPL * r.explanation_value_score
        )

    self_match = results[0]
    others = sorted(results[1:], key=_composite, reverse=True)
    ranked = [self_match] + others

    source_counts: dict[str, int] = {}
    for r in ranked:
        key = str(r.candidate.source_type)
        source_counts[key] = source_counts.get(key, 0) + 1

    # ── Stage 7: Must-retrieve validation ────────────────────────────
    tier1_ids = {
        r.candidate.identifier for r in ranked if r.tier == TierLevel.Tier1
    }
    top10_ids = {r.candidate.identifier for r in ranked[:10]}
    missing = tier1_ids - top10_ids
    if missing:
        msg = f"Tier1 records missing from top-10: {missing}"
        logger.warning("Pipeline validation: {}", msg)
        warnings_list.append(msg)

    elapsed = time.monotonic() - t0
    return RetrievalResponse(
        seed=seed,
        results=ranked,
        total_candidates_considered=len(fused),
        metadata={
            "elapsed_seconds": round(elapsed, 3),
            "graph_nodes": len(graph.nodes),
            "graph_edges": len(graph.edges),
            "warnings": warnings_list,
            "source_counts": source_counts,
        },
    )
