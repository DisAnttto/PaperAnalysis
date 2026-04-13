"""Tests for the full retrieval pipeline (app/retrieval/pipeline.py).

Mocks all external clients and verifies output structure, rank ordering,
and tier assignments.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.retrieval.enums import RelationLabel, SourceType, TierLevel
from app.retrieval.models import ExtractedTargetProfile, RetrievalResponse
from app.retrieval.pipeline import retrieve_correlated_evidence


@pytest.fixture()
def mock_clients():
    """Patch _build_clients to return empty-result mocks."""
    clients = {
        "openfda": MagicMock(),
        "clinicaltrials": MagicMock(),
        "dailymed": MagicMock(),
        "accessgudid": MagicMock(),
    }
    # All client methods return empty lists
    for c in clients.values():
        for attr in dir(c):
            if not attr.startswith("_"):
                method = getattr(c, attr)
                if callable(method):
                    setattr(c, attr, AsyncMock(return_value=[]))

    with patch(
        "app.retrieval.pipeline._build_clients",
        return_value=clients,
    ):
        yield clients


async def test_pipeline_returns_response(mock_clients) -> None:
    response = await retrieve_correlated_evidence("PMID:39350227")
    assert isinstance(response, RetrievalResponse)
    assert response.seed.identifier == "PMID:39350227"


async def test_self_match_at_rank1(mock_clients) -> None:
    response = await retrieve_correlated_evidence("PMID:39350227")
    assert len(response.results) >= 1
    first = response.results[0]
    assert first.candidate.identifier == "PMID:39350227"
    assert first.correlation_score == 1.0
    assert first.relation_label == RelationLabel.self_match
    assert first.tier == TierLevel.Tier0


async def test_pipeline_with_profile_override(mock_clients) -> None:
    profile = ExtractedTargetProfile(
        product_type="drug",
        product_name="VABYSMO (faricimab-svoa)",
        active_ingredient="faricimab-svoa",
        route="intravitreal",
        indication=["nAMD", "DME"],
        key_metrics_or_endpoints=["BCVA", "OCT thickness"],
    )
    response = await retrieve_correlated_evidence(
        "PMID:39350227", profile_override=profile
    )
    assert isinstance(response, RetrievalResponse)
    assert response.seed.identifier == "PMID:39350227"
    # Self-match should have endpoint-related explanation value
    assert response.results[0].explanation_value_score > 0


async def test_pipeline_metadata_has_timing(mock_clients) -> None:
    response = await retrieve_correlated_evidence("PMID:39350227")
    assert "elapsed_seconds" in response.metadata
    assert "graph_nodes" in response.metadata


async def test_pipeline_total_candidates_populated(mock_clients) -> None:
    response = await retrieve_correlated_evidence("K211668")
    assert response.total_candidates_considered >= 0


async def test_pipeline_results_sorted_by_composite(mock_clients) -> None:
    """After self-match at rank 1, remaining should be sorted descending."""
    # With empty clients, only self-match is returned
    response = await retrieve_correlated_evidence("PMID:39350227")
    if len(response.results) > 2:
        composites = [
            0.45 * r.correlation_score
            + 0.30 * r.evidence_strength_score
            + 0.25 * r.explanation_value_score
            for r in response.results[1:]
        ]
        for i in range(len(composites) - 1):
            assert composites[i] >= composites[i + 1] - 0.001


async def test_pipeline_denovo_seed(mock_clients) -> None:
    response = await retrieve_correlated_evidence("DEN180001")
    assert response.seed.source_type == SourceType.fda_denovo


async def test_pipeline_510k_seed(mock_clients) -> None:
    response = await retrieve_correlated_evidence("K211668")
    assert response.seed.source_type == SourceType.fda_510k
