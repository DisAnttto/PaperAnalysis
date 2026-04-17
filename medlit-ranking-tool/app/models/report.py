"""Report generation models for structured output."""

from typing import Any

from pydantic import BaseModel, Field


class ReportSection(BaseModel):
    """A single section of a generated report."""

    heading: str
    content: str
    section_type: str = "text"  # text, table, prisma


class PRISMAFlowCounts(BaseModel):
    """PRISMA-style record counts at each stage of the retrieval flow."""

    records_identified: dict[str, int] = Field(default_factory=dict)
    total_identified: int = 0
    duplicates_removed: int = 0
    records_screened: int = 0
    records_excluded_triage: int = 0
    full_text_assessed: int = 0
    full_text_excluded: int = 0
    studies_included: int = 0


class EvidenceTableRow(BaseModel):
    """A row in the evidence summary table."""

    uid: str
    title: str
    source: str
    authors: str
    year: int | None = None
    study_type: str | None = None
    sample_size: int | None = None
    composite_score: float
    relevance_score: float
    evidence_quality_score: float
    key_findings: str = ""


class SearchReport(BaseModel):
    """Complete report generated from a search run."""

    title: str
    run_id: str | None = None
    query: str
    sections: list[ReportSection] = Field(default_factory=list)
    prisma: PRISMAFlowCounts = Field(default_factory=PRISMAFlowCounts)
    evidence_table: list[EvidenceTableRow] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
