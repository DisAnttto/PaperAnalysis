"""FDA direct-download client for PDF artifacts (510k summaries, SSEDs, De Novo decisions)."""

from __future__ import annotations

import re

import httpx
from loguru import logger

from app.core.config import Settings

_ACCESS_DATA = "https://www.accessdata.fda.gov"


class FDADownloadClient:
    """Async client for fetching FDA PDF documents from accessdata.fda.gov."""

    def __init__(self, settings: Settings) -> None:
        _ = settings
        self._http = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    async def fetch_510k_summary(self, k_number: str) -> bytes | None:
        """Fetch 510(k) decision summary PDF.

        Tries the standard path pattern ``/cdrh_docs/pdf{yy}/{k_number}.pdf``
        where ``{yy}`` is derived from the K-number year digits.
        """
        k = k_number.upper().lstrip("K")
        yy = k[:2] if len(k) >= 2 else k
        url = f"{_ACCESS_DATA}/cdrh_docs/pdf{yy}/{k_number}.pdf"
        return await self._fetch_bytes(url)

    async def fetch_denovo_decision(self, den_number: str) -> bytes | None:
        """Fetch De Novo decision review PDF."""
        url = f"{_ACCESS_DATA}/cdrh_docs/reviews/{den_number}.pdf"
        return await self._fetch_bytes(url)

    async def fetch_ssed(self, pma_number: str) -> bytes | None:
        """Fetch Supplement Summary of Evidence and Determination (SSED) PDF."""
        m = re.match(r"[A-Z]+(\d+)", pma_number.upper())
        n = m.group(1)[0] if m else ""
        url = f"{_ACCESS_DATA}/cdrh_docs/pdf{n}/{pma_number}B.pdf"
        return await self._fetch_bytes(url)

    async def _fetch_bytes(self, url: str) -> bytes | None:
        logger.debug("FDA download GET {}", url)
        try:
            r = await self._http.get(url)
            if r.status_code == 404:
                logger.debug("FDA download 404: {}", url)
                return None
            r.raise_for_status()
            return r.content
        except httpx.HTTPStatusError as exc:
            logger.warning("FDA download error {}: {}", url, exc)
            return None
