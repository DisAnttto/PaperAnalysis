"""Unit tests for FDADownloadClient using httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from app.clients.fda_downloads import FDADownloadClient
from app.core.config import Settings


def _mock_transport(responses: dict[str, tuple[int, bytes | None]]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for substring, (status, body) in responses.items():
            if substring in url:
                content = body if body is not None else b""
                return httpx.Response(status, content=content)
        return httpx.Response(404, content=b"")

    return httpx.MockTransport(handler)


def _client_with(responses: dict[str, tuple[int, bytes | None]]) -> FDADownloadClient:
    s = Settings()
    c = FDADownloadClient(s)
    c._http = httpx.AsyncClient(transport=_mock_transport(responses), follow_redirects=True)
    return c


@pytest.mark.asyncio
async def test_fetch_510k_summary_success() -> None:
    pdf_bytes = b"%PDF-1.4 fake content"
    c = _client_with({"K211668.pdf": (200, pdf_bytes)})
    result = await c.fetch_510k_summary("K211668")
    assert result == pdf_bytes


@pytest.mark.asyncio
async def test_fetch_510k_summary_404() -> None:
    c = _client_with({})
    result = await c.fetch_510k_summary("K999999")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_denovo_decision_success() -> None:
    pdf_bytes = b"%PDF de-novo decision"
    c = _client_with({"DEN180001.pdf": (200, pdf_bytes)})
    result = await c.fetch_denovo_decision("DEN180001")
    assert result == pdf_bytes


@pytest.mark.asyncio
async def test_fetch_denovo_decision_404() -> None:
    c = _client_with({})
    result = await c.fetch_denovo_decision("DEN999999")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_ssed_success() -> None:
    pdf_bytes = b"%PDF ssed content"
    c = _client_with({"P210001B.pdf": (200, pdf_bytes)})
    result = await c.fetch_ssed("P210001")
    assert result == pdf_bytes


@pytest.mark.asyncio
async def test_fetch_ssed_404() -> None:
    c = _client_with({})
    result = await c.fetch_ssed("P999999")
    assert result is None


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fetch_510k_summary() -> None:
    from app.core.config import settings
    c = FDADownloadClient(settings)
    result = await c.fetch_510k_summary("K211668")
    # Result may be None if the PDF doesn't exist at the guessed path
    assert result is None or isinstance(result, bytes)
