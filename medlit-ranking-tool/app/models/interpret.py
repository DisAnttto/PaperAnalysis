"""Natural-language finding parse models."""

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Natural-language finding parse models
# ---------------------------------------------------------------------------

class FindingParseRequest(BaseModel):
    """Free-text clinical finding to be parsed by LLM."""

    text: str = Field(..., min_length=1)


class FindingParseResponse(BaseModel):
    """LLM-extracted fields from natural language — fills main search sidebar."""

    # Finding comparison fields (metric/value context)
    metric_name: str | None = None
    metric_unit: str | None = None
    timepoint: str | None = None
    observed_value: float | None = None
    control_value: float | None = None
    is_significant: bool | None = None
    clinical_context: str | None = None
    procedure: str | None = None

    # Main search fields — populated into the sidebar directly
    query: str | None = None                     # suggested PubMed query string
    target_type: str | None = None               # "device" | "drug" | "both"
    product_name: str | None = None              # -> f-product-name
    manufacturer: str | None = None              # -> f-manufacturer
    device_category: str | None = None           # -> f-device-category
    intended_use: str | None = None              # -> f-intended-use
    indications: list[str] | None = None         # -> f-indications (comma-joined)
    active_ingredient: str | None = None         # -> f-active-ingredient
    drug_class: str | None = None                # -> f-drug-class
    route: str | None = None                     # -> f-route
    metrics_of_interest: list[str] | None = None # added as metric chips
    seed_identifier: str | None = None           # -> ev-seed (PMID:xxx / K-number / NCT / DEN)
    keywords: list[str] | None = None            # -> f-keywords (comma-joined)

    # Step 1 intermediate (for UI: specs vs intent vs clinical finding)
    step1_product_context: dict[str, Any] | None = None
    step1_clinical_finding: dict[str, Any] | None = None
    step1_search_goals: list[str] | None = None

    raw_text: str
