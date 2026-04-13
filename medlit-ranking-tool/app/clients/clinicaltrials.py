"""ClinicalTrials.gov API v2 client."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings


class ClinicalTrialsClient:
    """Async client for ClinicalTrials.gov v2 REST API."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.CLINICALTRIALS_BASE_URL.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        logger.debug("ClinicalTrials GET {}", url)
        r = await self._http.get(url, params=params or {})
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def get_study(self, nct_id: str) -> dict[str, Any]:
        """Fetch a single study by NCT ID."""
        data = await self._get(f"/studies/{nct_id}")
        return data if isinstance(data, dict) else {}

    async def search_studies(
        self,
        query: str | None = None,
        condition: str | None = None,
        intervention: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search studies using ClinicalTrials.gov v2 query parameters."""
        params: dict[str, Any] = {"pageSize": limit, "format": "json"}
        if query:
            params["query.term"] = query
        if condition:
            params["query.cond"] = condition
        if intervention:
            params["query.intr"] = intervention
        data = await self._get("/studies", params)
        if isinstance(data, dict):
            return data.get("studies", [])
        return []
