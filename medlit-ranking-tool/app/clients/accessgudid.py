"""AccessGUDID API client for device identity lookup."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings


class AccessGUDIDClient:
    """Async client for NLM AccessGUDID device lookup/search."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ACCESSGUDID_BASE_URL.rstrip("/")
        self._http = httpx.AsyncClient(timeout=30.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        logger.debug("AccessGUDID GET {}", url)
        r = await self._http.get(url, params=params or {})
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def lookup_device(self, di: str) -> dict[str, Any]:
        """Look up a device by Device Identifier (DI)."""
        data = await self._get("/devices/lookup.json", {"di": di})
        return data if isinstance(data, dict) else {}

    async def search_devices(
        self, brand_name: str | None = None, company: str | None = None
    ) -> list[dict[str, Any]]:
        """Search devices by brand name and/or company name."""
        params: dict[str, Any] = {}
        if brand_name:
            params["brand_name"] = brand_name
        if company:
            params["company_name"] = company
        data = await self._get("/devices.json", params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("devices", data.get("results", []))
        return []
