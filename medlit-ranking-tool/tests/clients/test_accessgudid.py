"""Unit tests for AccessGUDIDClient using httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from app.clients.accessgudid import AccessGUDIDClient
from app.core.config import Settings


def _mock_transport(responses: dict[str, tuple[int, object]]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for substring, (status, body) in responses.items():
            if substring in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _client_with(responses: dict[str, tuple[int, object]]) -> AccessGUDIDClient:
    s = Settings(ACCESSGUDID_BASE_URL="https://accessgudid.nlm.nih.gov/api/v2")
    c = AccessGUDIDClient(s)
    c._http = httpx.AsyncClient(transport=_mock_transport(responses))
    return c


@pytest.mark.asyncio
async def test_lookup_device_success() -> None:
    payload = {"device": {"deviceIdentifier": "00884523203278", "brandName": "TestLens"}}
    c = _client_with({"lookup.json": (200, payload)})
    result = await c.lookup_device("00884523203278")
    assert result.get("device", {}).get("brandName") == "TestLens"


@pytest.mark.asyncio
async def test_lookup_device_404() -> None:
    c = _client_with({"lookup.json": (404, {})})
    result = await c.lookup_device("00000000000000")
    assert result == {}


@pytest.mark.asyncio
async def test_search_devices_list_response() -> None:
    payload = [{"deviceIdentifier": "001"}, {"deviceIdentifier": "002"}]
    c = _client_with({"devices.json": (200, payload)})
    result = await c.search_devices(brand_name="Lens")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_search_devices_dict_response() -> None:
    payload = {"devices": [{"deviceIdentifier": "001"}]}
    c = _client_with({"devices.json": (200, payload)})
    result = await c.search_devices(brand_name="Lens")
    assert len(result) == 1


@pytest.mark.asyncio
async def test_search_devices_empty() -> None:
    c = _client_with({"devices.json": (404, {})})
    result = await c.search_devices(brand_name="NoSuchDevice")
    assert result == []


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_lookup_device() -> None:
    from app.core.config import settings
    c = AccessGUDIDClient(settings)
    result = await c.lookup_device("00884523203278")
    assert isinstance(result, dict)
