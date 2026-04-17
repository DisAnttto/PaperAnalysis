"""Stored paper metadata returned from ingestion sources."""

import hashlib
from datetime import date

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """Raw paper metadata persisted after ingestion.

    Fields come from PubMed / CrossRef / other sources — not from LLM
    extraction.  The extraction step reads a Paper and produces an
    ExtractionResult (see extraction.py).

    ``identifier`` is a universal key across all sources (PMID for PubMed,
    NCT ID for ClinicalTrials, K-number for 510(k), etc.).  ``pmid`` is kept
    for backward compatibility and is set only for PubMed papers.
    """

    pmid: str | None = None
    doi: str | None = None
    identifier: str | None = None
    source: str = Field(default="PubMed", description="Origin database: PubMed, openFDA, ClinicalTrials, DailyMed, AccessGUDID")
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    published_date: date | None = None
    mesh_terms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source_url: str | None = None

    @property
    def uid(self) -> str:
        """Universal identifier: pmid when available, else identifier, else title hash.

        The title fallback uses SHA-256 (truncated to 16 hex chars) so the UID
        is stable across Python processes and restarts.  Python's built-in
        hash() is randomized per-process (PEP 456) and must not be used here.
        """
        if self.pmid:
            return self.pmid
        if self.identifier:
            return self.identifier
        return hashlib.sha256(self.title.encode()).hexdigest()[:16]
