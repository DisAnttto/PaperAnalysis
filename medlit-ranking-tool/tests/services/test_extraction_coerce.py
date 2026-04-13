"""Tests for LLM extraction JSON coercion before Pydantic validation."""

from app.models.extraction import ExtractionResult
from app.models.paper import Paper
from app.services.extraction import _coerce_llm_output


def _minimal_valid_base() -> dict:
    return {
        "schema_version": "1.0.0",
        "paper_synopsis": {
            "value": "Synopsis text here.",
            "supporting_evidence_snippets": ["snippet"],
        },
        "topical_relevance": {
            "label": "high",
            "evidence_snippet": "topical",
            "evidence_section": "abstract",
        },
        "study": {
            "study_type": {
                "value": "prospective_cohort",
                "evidence_snippet": "prospective cohort",
                "evidence_section": "abstract",
            },
            "evidence_domain": {
                "value": "human_clinical",
                "evidence_snippet": "patients",
                "evidence_section": "abstract",
            },
        },
    }


def test_coerce_qualitative_findings_null_evidence() -> None:
    paper = Paper(
        pmid="39350227",
        title="Faricimab for nAMD",
        abstract="Intravitreal faricimab was used. BCVA improved.",
    )
    data = _minimal_valid_base()
    data["qualitative_findings"] = [
        {
            "tag": "efficacy",
            "status": "present",
            "evidence_snippet": None,
            "evidence_section": None,
        },
    ]
    data["drug"] = {
        "active_ingredient": {
            "value": "faricimab",
            "evidence_snippet": "faricimab",
            "evidence_section": "abstract",
        },
        "drug_class": {
            "value": "anti-VEGF",
            "evidence_snippet": "VEGF-A",
            "evidence_section": "abstract",
        },
        "route": {
            "value": "intravitreal",
            "evidence_snippet": "intravitreal",
            "evidence_section": "abstract",
        },
    }
    data["metrics"] = [
        {
            "metric_name_normalized": "bcva",
            "metric_name_raw": "BCVA",
            "metric_category": "efficacy",
            "value_type": "numeric",
            "numeric_value": 0.5,
            "evidence_snippet": "BCVA data",
            "evidence_section": "abstract",
        },
    ]

    _coerce_llm_output(data, paper)
    result = ExtractionResult.model_validate(data)
    assert len(result.qualitative_findings) == 1
    assert result.qualitative_findings[0].evidence_snippet
    assert result.qualitative_findings[0].evidence_section.value == "unknown"


def test_coerce_drug_nested_null_evidence_snippet() -> None:
    paper = Paper(pmid="1", title="T", abstract="Abstract body " * 20)
    data = _minimal_valid_base()
    data["drug"] = {
        "active_ingredient": {
            "value": "faricimab",
            "evidence_snippet": None,
            "evidence_section": None,
        },
        "drug_class": {
            "value": "anti-VEGF bispecific",
            "evidence_snippet": None,
            "evidence_section": None,
        },
    }
    _coerce_llm_output(data, paper)
    result = ExtractionResult.model_validate(data)
    assert result.drug is not None
    assert result.drug.active_ingredient is not None
    assert result.drug.active_ingredient.evidence_snippet
    assert result.drug.drug_class is not None
    assert result.drug.drug_class.evidence_section.value == "abstract"


def test_sanitize_device_strips_unknown_keys_and_salvages_model_number() -> None:
    """LLMs often emit extra device.* keys (forbidden by DeviceExtraction)."""
    paper = Paper(pmid="37641668", title="IOL study", abstract="Trifocal IOL " * 30)
    data = _minimal_valid_base()
    data["device"] = {
        "product_name": {
            "value": "AcrySof IQ PanOptix",
            "evidence_snippet": "PanOptix",
            "evidence_section": "title",
        },
        "model_number": {
            "value": "TFNT00",
            "evidence_snippet": "TFNT00",
            "evidence_section": "abstract",
        },
        "device_type": {
            "value": "trifocal intraocular lens",
            "evidence_snippet": "trifocal",
            "evidence_section": "title",
        },
        "material": {
            "value": None,
            "evidence_snippet": None,
            "evidence_section": None,
        },
        "model_number_extra": {"value": "should be removed"},
    }
    _coerce_llm_output(data, paper)
    result = ExtractionResult.model_validate(data)
    assert result.device is not None
    assert result.device.product_name is not None
    assert result.device.key_features is not None
    assert "TFNT00" in result.device.key_features.value


def test_coerce_binary_metric_invalid_text_value() -> None:
    data = _minimal_valid_base()
    data["metrics"] = [
        {
            "metric_name_normalized": "dry_macula",
            "metric_name_raw": "dry macula",
            "metric_category": "efficacy",
            "value_type": "binary",
            "text_value": "present",
            "evidence_snippet": "x",
            "evidence_section": "abstract",
        },
    ]
    _coerce_llm_output(data, None)
    result = ExtractionResult.model_validate(data)
    assert result.metrics[0].text_value == "unclear"
