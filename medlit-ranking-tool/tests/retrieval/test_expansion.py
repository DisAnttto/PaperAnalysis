"""Tests for expand_candidates in app/retrieval/expansion.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.retrieval.enums import SourceType
from app.retrieval.expansion import _classify_seed, expand_candidates
from app.retrieval.models import ExtractedTargetProfile, SeedRecord


# ---------------------------------------------------------------------------
# _classify_seed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("PMID:39350227", "pubmed"),
        ("PMC:12345678", "pubmed"),
        ("NCT04709952", "trial"),
        ("K211668", "510k"),
        ("DEN180001", "denovo"),
        ("PMA210001", "pma"),
        ("NDA210001", "drug"),
        ("BLA761235", "drug"),
        ("UNKNOWN:123", "unknown"),
    ],
)
def test_classify_seed(identifier: str, expected: str) -> None:
    assert _classify_seed(identifier) == expected


# ---------------------------------------------------------------------------
# expand_candidates — mock all clients
# ---------------------------------------------------------------------------

def _make_seed(identifier: str, source_type=SourceType.pubmed_paper) -> SeedRecord:
    return SeedRecord(source_type=source_type, source_name="test", identifier=identifier)


def _make_profile(**kwargs) -> ExtractedTargetProfile:
    defaults = dict(
        product_type="device",
        product_name="TestLens",
        indication=["AMD"],
        key_metrics_or_endpoints=["BCVA"],
    )
    defaults.update(kwargs)
    return ExtractedTargetProfile(**defaults)


@pytest.mark.asyncio
async def test_expand_calls_openfda_for_device_seed() -> None:
    seed = _make_seed("K211668", source_type=SourceType.fda_510k)
    profile = _make_profile(product_type="device")

    openfda = MagicMock()
    openfda.search_device = AsyncMock(return_value=[])
    clients = {"openfda": openfda}

    result = await expand_candidates(seed, profile, clients)
    openfda.search_device.assert_called_once()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_expand_calls_drug_label_for_drug_seed() -> None:
    seed = _make_seed("BLA761235", source_type=SourceType.fda_label)
    profile = _make_profile(product_type="drug", active_ingredient="faricimab")

    openfda = MagicMock()
    openfda.search_drug_label = AsyncMock(return_value=[])
    clients = {"openfda": openfda}

    result = await expand_candidates(seed, profile, clients)
    openfda.search_drug_label.assert_called_once()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_expand_calls_clinicaltrials() -> None:
    seed = _make_seed("PMID:001")
    profile = _make_profile(product_type="drug", indication=["AMD", "DME"])

    ct = MagicMock()
    ct.search_studies = AsyncMock(return_value=[])
    clients = {"clinicaltrials": ct}

    await expand_candidates(seed, profile, clients)
    ct.search_studies.assert_called_once()


@pytest.mark.asyncio
async def test_expand_converts_510k_result_to_evidence_record() -> None:
    seed = _make_seed("K211668", source_type=SourceType.fda_510k)
    profile = _make_profile(product_type="device")

    openfda = MagicMock()
    openfda.search_device = AsyncMock(
        return_value=[{"k_number": "K211668", "device_name": "RetinalLens", "applicant": "ACME"}]
    )
    clients = {"openfda": openfda}

    result = await expand_candidates(seed, profile, clients)
    device_recs = [r for r in result if r.source_type == SourceType.fda_510k]
    assert len(device_recs) == 1
    assert device_recs[0].identifier == "510K:K211668"


@pytest.mark.asyncio
async def test_expand_converts_trial_result_to_evidence_record() -> None:
    seed = _make_seed("PMID:001")
    profile = _make_profile(product_type="drug", indication=["AMD"])

    ct = MagicMock()
    ct.search_studies = AsyncMock(
        return_value=[
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT04709952", "briefTitle": "TENAYA"},
                    "conditionsModule": {"conditions": ["AMD"]},
                    "armsInterventionsModule": {"interventions": []},
                    "descriptionModule": {},
                }
            }
        ]
    )
    clients = {"clinicaltrials": ct}

    result = await expand_candidates(seed, profile, clients)
    trial_recs = [r for r in result if r.source_type == SourceType.clinicaltrials]
    assert len(trial_recs) == 1
    assert "NCT04709952" in trial_recs[0].identifier


@pytest.mark.asyncio
async def test_expand_graceful_on_client_failure() -> None:
    seed = _make_seed("K000001", source_type=SourceType.fda_510k)
    profile = _make_profile(product_type="device")

    openfda = MagicMock()
    openfda.search_device = AsyncMock(side_effect=RuntimeError("API down"))
    clients = {"openfda": openfda}

    result = await expand_candidates(seed, profile, clients)
    assert isinstance(result, list)
