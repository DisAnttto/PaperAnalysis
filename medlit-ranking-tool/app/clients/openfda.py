"""openFDA API client for device and drug queries."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings


class OpenFDAClient:
    """Async client for openFDA device and drug endpoints."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.OPENFDA_BASE_URL.rstrip("/")
        self.api_key = settings.OPENFDA_API_KEY
        self._http = httpx.AsyncClient(timeout=30.0)

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        p: dict[str, Any] = {}
        if self.api_key:
            p["api_key"] = self.api_key
        if extra:
            p.update(extra)
        return p

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.debug("openFDA GET {} params={}", url, params)
        r = await self._http.get(url, params=params)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def search_510k(self, k_number: str) -> dict[str, Any]:
        """Fetch a single 510(k) record by K-number."""
        params = self._params({"search": f'k_number:"{k_number}"', "limit": 1})
        data = await self._get("/device/510k.json", params)
        results = data.get("results", [])
        return results[0] if results else {}

    async def search_pma(self, pma_number: str) -> dict[str, Any]:
        """Fetch a single PMA record by PMA number."""
        params = self._params({"search": f'pma_number:"{pma_number}"', "limit": 1})
        data = await self._get("/device/pma.json", params)
        results = data.get("results", [])
        return results[0] if results else {}

    async def search_device(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search 510(k) device records by free-text query."""
        params = self._params({"search": query, "limit": limit})
        data = await self._get("/device/510k.json", params)
        return data.get("results", [])

    async def search_drug_label(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search FDA drug labeling records."""
        params = self._params({"search": query, "limit": limit})
        data = await self._get("/drug/label.json", params)
        return data.get("results", [])

    async def search_drug_event(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search FDA drug adverse event records."""
        params = self._params({"search": query, "limit": limit})
        data = await self._get("/drug/event.json", params)
        return data.get("results", [])
