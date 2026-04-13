"""DailyMed API client for SPL label queries."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings


class DailyMedClient:
    """Async client for NLM DailyMed SPL services."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.DAILYMED_BASE_URL.rstrip("/")
        self._http = httpx.AsyncClient(timeout=30.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        logger.debug("DailyMed GET {}", url)
        r = await self._http.get(url, params=params or {})
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def get_spl_by_setid(self, setid: str) -> dict[str, Any]:
        """Fetch a Structured Product Label by set ID."""
        data = await self._get(f"/spls/{setid}.json")
        return data if isinstance(data, dict) else {}

    async def search_spls(self, drug_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search SPL records by drug name, returning the data list."""
        data = await self._get("/spls.json", {"drug_name": drug_name, "pagesize": limit})
        if isinstance(data, dict):
            return data.get("data", [])
        return []

    async def get_label_sections(self, setid: str) -> dict[str, Any]:
        """Fetch a SPL and return its sections keyed by section name."""
        data = await self._get(f"/spls/{setid}.json")
        if not isinstance(data, dict):
            return {}
        sections: dict[str, Any] = {}
        for section in data.get("sections", []):
            name = section.get("title") or section.get("name", "")
            if name:
                sections[name] = section
        return sections
