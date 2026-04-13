"""Unit tests for DailyMedClient using httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from app.clients.dailymed import DailyMedClient
from app.core.config import Settings


def _mock_transport(responses: dict[str, tuple[int, object]]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for substring, (status, body) in responses.items():
            if substring in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _client_with(responses: dict[str, tuple[int, object]]) -> DailyMedClient:
    s = Settings(DAILYMED_BASE_URL="https://dailymed.nlm.nih.gov/dailymed/services/v2")
    c = DailyMedClient(s)
    c._http = httpx.AsyncClient(transport=_mock_transport(responses))
    return c


@pytest.mark.asyncio
async def test_get_spl_by_setid_success() -> None:
    setid = "aaaa-bbbb-cccc"
    payload = {"setId": setid, "sections": [{"title": "Indications", "text": "..."}]}
    c = _client_with({setid: (200, payload)})
    result = await c.get_spl_by_setid(setid)
    assert result.get("setId") == setid


@pytest.mark.asyncio
async def test_get_spl_by_setid_404() -> None:
    c = _client_with({"spls/bad-id": (404, {})})
    result = await c.get_spl_by_setid("bad-id")
    assert result == {}


@pytest.mark.asyncio
async def test_search_spls_returns_data() -> None:
    payload = {"data": [{"setid": "id1", "drug_name": "Faricimab"}, {"setid": "id2", "drug_name": "Faricimab 2"}]}
    c = _client_with({"spls.json": (200, payload)})
    result = await c.search_spls("faricimab")
    assert len(result) == 2
    assert result[0]["drug_name"] == "Faricimab"


@pytest.mark.asyncio
async def test_search_spls_empty() -> None:
    c = _client_with({"spls.json": (404, {})})
    result = await c.search_spls("unknowndrugxyz")
    assert result == []


@pytest.mark.asyncio
async def test_get_label_sections_extracts_titles() -> None:
    setid = "aaaa-1111"
    payload = {
        "setId": setid,
        "sections": [
            {"title": "Indications and Usage", "text": "..."},
            {"title": "Warnings", "text": "..."},
        ],
    }
    c = _client_with({setid: (200, payload)})
    result = await c.get_label_sections(setid)
    assert "Indications and Usage" in result
    assert "Warnings" in result


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_search_spls() -> None:
    from app.core.config import settings
    c = DailyMedClient(settings)
    result = await c.search_spls("aspirin", limit=3)
    assert isinstance(result, list)
