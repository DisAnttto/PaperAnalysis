"""Shared types for the ophthalmology normalization layer."""

from dataclasses import dataclass, field
from enum import StrEnum


class NormalizationMethod(StrEnum):
    DICTIONARY = "dictionary"
    RULE = "rule"
    LLM = "llm"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NormResult:
    """Single-value normalization result."""

    raw: str
    canonical: str | None
    confidence: float
    method: NormalizationMethod


@dataclass(frozen=True)
class NormListResult:
    """Multi-value normalization result (e.g. a list of indications)."""

    raw: list[str]
    canonical: list[str]
    confidence: float
    method: NormalizationMethod

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", list(self.raw))
        object.__setattr__(self, "canonical", list(self.canonical))
