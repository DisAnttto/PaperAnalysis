"""OpenAlex API client for academic literature search.

OpenAlex (https://openalex.org) provides free, open metadata for ~250M+
scholarly works.  It complements PubMed by covering non-biomedical journals,
preprints, and conference papers with richer DOI/citation metadata.

The polite pool (https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication)
requires a ``mailto`` parameter.  We use the NCBI_EMAIL from config for this.

No API key is required.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings

_BASE_URL = "https://api.openalex.org"


class OpenAlexClient:
    """Async client for the OpenAlex REST API."""

    def __init__(self, settings: Settings) -> None:
        self._email = (settings.NCBI_EMAIL or "").strip()
        self._http = httpx.AsyncClient(timeout=30.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{_BASE_URL}{path}"
        p = dict(params or {})
        if self._email:
            p["mailto"] = self._email
        logger.debug("OpenAlex GET {}", url)
        r = await self._http.get(url, params=p)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def search_works(
        self,
        query: str,
        *,
        limit: int = 25,
        filter_str: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search OpenAlex works by free-text query.

        Optional ``filter_str`` follows OpenAlex filter syntax, e.g.:
          "type:article,publication_year:>2020"
        """
        params: dict[str, Any] = {
            "search": query,
            "per_page": min(limit, 200),
        }
        if filter_str:
            params["filter"] = filter_str
        data = await self._get("/works", params)
        if isinstance(data, dict):
            return data.get("results", [])
        return []

    async def get_work_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Fetch a single work by DOI."""
        clean = doi.strip().lower()
        if clean.startswith("https://doi.org/"):
            clean = clean[len("https://doi.org/"):]
        elif clean.startswith("doi:"):
            clean = clean[4:]
        data = await self._get(f"/works/https://doi.org/{clean}")
        if isinstance(data, dict) and data.get("id"):
            return data
        return None

    async def get_work_by_pmid(self, pmid: str) -> dict[str, Any] | None:
        """Fetch a single work by PubMed ID."""
        data = await self._get(f"/works/pmid:{pmid}")
        if isinstance(data, dict) and data.get("id"):
            return data
        return None
