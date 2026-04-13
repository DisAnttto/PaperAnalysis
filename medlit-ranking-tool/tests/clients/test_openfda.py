"""Unit tests for OpenFDAClient using httpx mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from app.clients.openfda import OpenFDAClient
from app.core.config import Settings


def _mock_transport(responses: dict[str, tuple[int, dict]]):
    """Build an httpx MockTransport that maps URL substrings to responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for substring, (status, body) in responses.items():
            if substring in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _client_with(responses: dict[str, tuple[int, dict]]) -> OpenFDAClient:
    s = Settings(OPENFDA_API_KEY="", OPENFDA_BASE_URL="https://api.fda.gov")
    c = OpenFDAClient(s)
    c._http = httpx.AsyncClient(transport=_mock_transport(responses))
    return c


@pytest.mark.asyncio
async def test_search_510k_success() -> None:
    payload = {"results": [{"k_number": "K210001", "device_name": "TestDevice"}]}
    c = _client_with({"510k.json": (200, payload)})
    result = await c.search_510k("K210001")
    assert result["k_number"] == "K210001"


@pytest.mark.asyncio
async def test_search_510k_not_found() -> None:
    c = _client_with({"510k.json": (404, {})})
    result = await c.search_510k("K999999")
    assert result == {}


@pytest.mark.asyncio
async def test_search_pma_success() -> None:
    payload = {"results": [{"pma_number": "P210001", "device_name": "PMADevice"}]}
    c = _client_with({"pma.json": (200, payload)})
    result = await c.search_pma("P210001")
    assert result["pma_number"] == "P210001"


@pytest.mark.asyncio
async def test_search_device_returns_list() -> None:
    payload = {"results": [{"k_number": "K001"}, {"k_number": "K002"}]}
    c = _client_with({"510k.json": (200, payload)})
    result = await c.search_device("retinal", limit=2)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_search_device_empty() -> None:
    c = _client_with({"510k.json": (404, {})})
    result = await c.search_device("nonexistent")
    assert result == []


@pytest.mark.asyncio
async def test_search_drug_label_success() -> None:
    payload = {"results": [{"openfda": {"brand_name": ["HUMIRA"]}}]}
    c = _client_with({"label.json": (200, payload)})
    result = await c.search_drug_label("adalimumab")
    assert len(result) == 1


@pytest.mark.asyncio
async def test_search_drug_event_success() -> None:
    payload = {"results": [{"safetyreportid": "12345"}]}
    c = _client_with({"event.json": (200, payload)})
    result = await c.search_drug_event("aspirin")
    assert result[0]["safetyreportid"] == "12345"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_search_510k() -> None:
    """Live smoke test — skipped unless -m live is passed."""
    from app.core.config import settings
    c = OpenFDAClient(settings)
    result = await c.search_510k("K211668")
    assert isinstance(result, dict)
