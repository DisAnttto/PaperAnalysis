"""Unit tests for ClinicalTrialsClient using httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from app.clients.clinicaltrials import ClinicalTrialsClient
from app.core.config import Settings


def _mock_transport(responses: dict[str, tuple[int, object]]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for substring, (status, body) in responses.items():
            if substring in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _client_with(responses: dict[str, tuple[int, object]]) -> ClinicalTrialsClient:
    s = Settings(CLINICALTRIALS_BASE_URL="https://clinicaltrials.gov/api/v2")
    c = ClinicalTrialsClient(s)
    c._http = httpx.AsyncClient(
        transport=_mock_transport(responses),
        headers={"Accept": "application/json"},
    )
    return c


@pytest.mark.asyncio
async def test_get_study_success() -> None:
    nct = "NCT04709952"
    payload = {"protocolSection": {"identificationModule": {"nctId": nct, "briefTitle": "TENAYA"}}}
    c = _client_with({nct: (200, payload)})
    result = await c.get_study(nct)
    assert result.get("protocolSection", {}).get("identificationModule", {}).get("nctId") == nct


@pytest.mark.asyncio
async def test_get_study_404() -> None:
    c = _client_with({"NCT00000001": (404, {})})
    result = await c.get_study("NCT00000001")
    assert result == {}


@pytest.mark.asyncio
async def test_search_studies_returns_list() -> None:
    payload = {
        "studies": [
            {"protocolSection": {"identificationModule": {"nctId": "NCT001"}}},
            {"protocolSection": {"identificationModule": {"nctId": "NCT002"}}},
        ]
    }
    c = _client_with({"/studies": (200, payload)})
    result = await c.search_studies(condition="AMD", limit=5)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_search_studies_empty() -> None:
    c = _client_with({"/studies": (404, {})})
    result = await c.search_studies(query="nonexistent condition xyz")
    assert result == []


@pytest.mark.asyncio
async def test_search_studies_passes_params() -> None:
    """Verify query params are forwarded (inspect request URL via MockTransport)."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"studies": []})

    s = Settings(CLINICALTRIALS_BASE_URL="https://clinicaltrials.gov/api/v2")
    c = ClinicalTrialsClient(s)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"Accept": "application/json"})
    await c.search_studies(query="faricimab", condition="nAMD", intervention="VABYSMO", limit=7)
    assert captured
    url_str = str(captured[0].url)
    assert "faricimab" in url_str
    assert "nAMD" in url_str


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_search_studies() -> None:
    from app.core.config import settings
    c = ClinicalTrialsClient(settings)
    result = await c.search_studies(condition="age-related macular degeneration", limit=3)
    assert isinstance(result, list)
