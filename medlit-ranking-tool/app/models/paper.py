from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """Represents a single medical literature paper."""

    pmid: Optional[str] = None
    doi: Optional[str] = None
    title: str
    abstract: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    journal: Optional[str] = None
    published_date: Optional[date] = None
    keywords: list[str] = Field(default_factory=list)
    source_url: Optional[str] = None


class RankedPaper(Paper):
    """A paper augmented with ranking scores."""

    relevance_score: float = 0.0
    novelty_score: float = 0.0
    evidence_level: Optional[str] = None
    composite_score: float = 0.0
    rank: Optional[int] = None
    summary: Optional[str] = None
