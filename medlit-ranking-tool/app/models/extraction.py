"""Pydantic models for LLM extraction output.

Mirrors ``docs/extraction_schema.json`` (v1.0.0) with the exception of the
``regulatory`` section, which is intentionally excluded from the Python
model layer.  Every non-null extracted value carries an evidence snippet
and a section tag so downstream consumers can trace it back to source text.

Both ``device`` and ``drug`` are optional/nullable on ``ExtractionResult``.
A paper may describe a device, a drug, both, or neither extractably — the LLM
must never fabricate empty sections.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class EvidenceSection(StrEnum):
    TITLE = "title"
    ABSTRACT = "abstract"
    UNKNOWN = "unknown"


class SourceScope(StrEnum):
    TITLE_ABSTRACT = "title_abstract"


class TopicalRelevanceLabel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StudyType(StrEnum):
    SYSTEMATIC_REVIEW = "systematic_review"
    META_ANALYSIS = "meta_analysis"
    RCT = "rct"
    PROSPECTIVE_COHORT = "prospective_cohort"
    RETROSPECTIVE_COHORT = "retrospective_cohort"
    CASE_CONTROL = "case_control"
    CASE_SERIES = "case_series"
    CASE_REPORT = "case_report"
    BENCH_STUDY = "bench_study"
    IN_VITRO_STUDY = "in_vitro_study"
    ANIMAL_STUDY = "animal_study"
    NARRATIVE_REVIEW = "narrative_review"
    UNKNOWN = "unknown"


class EvidenceDomain(StrEnum):
    HUMAN_CLINICAL = "human_clinical"
    ANIMAL = "animal"
    IN_VITRO = "in_vitro"
    BENCH = "bench"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ComparatorType(StrEnum):
    """Comparator arm for clinical evidence — feeds Evidence Quality."""

    ACTIVE = "active"
    SHAM = "sham"
    PLACEBO = "placebo"
    HISTORICAL = "historical"
    NONE = "none"
    UNKNOWN = "unknown"


class DeviceClass(StrEnum):
    """FDA-style device class for extracted devices."""

    CLASS_I = "class_i"
    CLASS_II = "class_ii"
    CLASS_III = "class_iii"
    UNKNOWN = "unknown"


class MetricCategory(StrEnum):
    SAFETY = "safety"
    EFFICACY = "efficacy"
    PERFORMANCE = "performance"
    DURABILITY = "durability"
    BIOCOMPATIBILITY = "biocompatibility"
    TOXICITY = "toxicity"
    ADVERSE_EVENT = "adverse_event"
    PHARMACOKINETICS = "pharmacokinetics"
    PHARMACODYNAMICS = "pharmacodynamics"
    OTHER = "other"


class MetricValueType(StrEnum):
    NUMERIC = "numeric"
    RANGE = "range"
    PERCENTAGE = "percentage"
    BINARY = "binary"
    TEXT = "text"


class FindingStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    MIXED = "mixed"
    UNCLEAR = "unclear"


# ---------------------------------------------------------------------------
# Evidence wrapper types — mirror $defs in extraction_schema.json
# ---------------------------------------------------------------------------

class EvidenceStr(BaseModel):
    """A non-null string value with its evidence trail."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


class EvidenceInt(BaseModel):
    """A non-null integer value with its evidence trail."""

    model_config = ConfigDict(extra="forbid")

    value: int = Field(ge=0)
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


class EvidenceStrList(BaseModel):
    """A non-null list of strings with its evidence trail."""

    model_config = ConfigDict(extra="forbid")

    value: list[str] = Field(min_length=1)
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


class EvidenceStudyType(BaseModel):
    """Study-type label with its evidence trail."""

    model_config = ConfigDict(extra="forbid")

    value: StudyType
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


class EvidenceDomainType(BaseModel):
    """Evidence-domain label with its evidence trail."""

    model_config = ConfigDict(extra="forbid")

    value: EvidenceDomain
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


# ---------------------------------------------------------------------------
# Section models
# ---------------------------------------------------------------------------

class PaperSynopsis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)
    supporting_evidence_snippets: list[str] = Field(min_length=1)


class TopicalRelevance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: TopicalRelevanceLabel
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


class DeviceExtraction(BaseModel):
    """Extracted device fields — raw evidence-grounded values from the LLM.

    Feeds the normalization layer (``app.normalization``) which produces a
    ``NormalizedDevice`` for scoring.  Fields map to Product Similarity
    sub-signals (ranking_spec §2.2).
    """

    model_config = ConfigDict(extra="forbid")

    product_name: EvidenceStr | None = None
    device_category: EvidenceStr | None = None
    manufacturer: EvidenceStr | None = None
    intended_use: EvidenceStr | None = None
    indications: EvidenceStrList | None = None
    anatomical_site: EvidenceStr | None = None
    material: EvidenceStr | None = None
    key_features: EvidenceStrList | None = None
    device_class: DeviceClass | None = None
    energy_source: EvidenceStr | None = None
    sterilization_method: EvidenceStr | None = None


class DrugExtraction(BaseModel):
    """Extracted drug fields — raw evidence-grounded values from the LLM.

    Feeds the normalization layer which produces a ``NormalizedDrug`` for
    scoring.  Optional: only populated when the paper describes a drug
    product.  Never fabricated by the LLM for device-only papers.
    """

    model_config = ConfigDict(extra="forbid")

    product_name: EvidenceStr | None = None
    active_ingredient: EvidenceStr | None = None
    drug_class: EvidenceStr | None = None
    route: EvidenceStr | None = None
    indications: EvidenceStrList | None = None
    formulation_features: EvidenceStrList | None = None


class StudyExtraction(BaseModel):
    """Study design and population — feeds Evidence Quality scoring
    (ranking_spec §2.4).
    """

    model_config = ConfigDict(extra="forbid")

    study_type: EvidenceStudyType
    evidence_domain: EvidenceDomainType
    sample_size: EvidenceInt | None = None
    population_description: EvidenceStr | None = None
    follow_up_duration: EvidenceStr | None = None
    follow_up_months: EvidenceInt | None = None
    comparator_type: ComparatorType | None = None


class ExtractedMetric(BaseModel):
    """A single outcome metric extracted from the paper.

    Factual only — no polarity or direction fields.  The ranker derives
    favorability from user-supplied target metrics (ranking_spec §2.3).
    """

    model_config = ConfigDict(extra="forbid")

    metric_name_normalized: str | None = None
    metric_name_raw: str | None = None
    metric_category: MetricCategory
    value_type: MetricValueType
    numeric_value: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    text_value: str | None = None
    unit: str | None = None
    confidence_interval_low: float | None = None
    confidence_interval_high: float | None = None
    p_value: float | None = Field(default=None, ge=0, le=1)
    timepoint: str | None = None
    comparator: str | None = None
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection

    @model_validator(mode="after")
    def _check_value_fields(self) -> "ExtractedMetric":
        """Enforce conditional requirements mirroring the JSON Schema
        allOf/if/then blocks.
        """
        match self.value_type:
            case MetricValueType.NUMERIC:
                if self.numeric_value is None:
                    raise ValueError(
                        "numeric_value is required when value_type='numeric'"
                    )
            case MetricValueType.PERCENTAGE:
                if self.numeric_value is None:
                    raise ValueError(
                        "numeric_value is required when value_type='percentage'"
                    )
                if not self.unit:
                    raise ValueError(
                        "unit is required when value_type='percentage'"
                    )
            case MetricValueType.RANGE:
                if self.value_min is None or self.value_max is None:
                    raise ValueError(
                        "value_min and value_max are required "
                        "when value_type='range'"
                    )
            case MetricValueType.TEXT:
                if not self.text_value:
                    raise ValueError(
                        "text_value is required when value_type='text'"
                    )
            case MetricValueType.BINARY:
                if self.text_value not in ("yes", "no", "unclear"):
                    raise ValueError(
                        "text_value must be 'yes', 'no', or 'unclear' "
                        "when value_type='binary'"
                    )
        return self


class QualitativeFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tag: str = Field(default="", description="Short keyword tag for the finding")
    status: FindingStatus = FindingStatus.UNCLEAR
    severity: str | None = None
    evidence_snippet: str = Field(min_length=1)
    evidence_section: EvidenceSection


# ---------------------------------------------------------------------------
# Top-level extraction result
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    """Complete structured extraction for a single paper.

    Validated against ``docs/extraction_schema.json`` v1.0.0.
    Regulatory section is intentionally omitted from the Python model.

    Both ``device`` and ``drug`` are optional.  A paper may describe a
    device, a drug, both, or neither extractably.  The LLM must set each
    to ``null`` rather than fabricating an empty object.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    source_scope: SourceScope = SourceScope.TITLE_ABSTRACT
    pmid: str | None = None
    doi: str | None = None
    paper_synopsis: PaperSynopsis
    topical_relevance: TopicalRelevance
    device: DeviceExtraction | None = None
    drug: DrugExtraction | None = None
    study: StudyExtraction
    metrics: list[ExtractedMetric] = Field(default_factory=list)
    qualitative_findings: list[QualitativeFinding] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
