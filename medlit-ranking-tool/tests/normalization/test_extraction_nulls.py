"""Tests for device=null / drug=null handling in ExtractionResult and normalization pipeline.

Covers:
- ExtractionResult with device=None (drug-only paper)
- ExtractionResult with drug=None (device-only paper)
- ExtractionResult with both device and drug present
- ExtractionResult with both device and drug null (neither extractable)
- normalize_extraction product_type inference
- schema validation: ensure extra keys are rejected
- brand-to-material confidence < direct-alias confidence
"""

import pytest
from pydantic import ValidationError

from app.models.extraction import (
    DeviceExtraction,
    DrugExtraction,
    EvidenceDomainType,
    EvidenceStr,
    EvidenceStrList,
    EvidenceStudyType,
    ExtractionResult,
    PaperSynopsis,
    StudyExtraction,
    TopicalRelevance,
)
from app.normalization import normalize_extraction
from app.normalization.materials import normalize_material


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ev(val: str) -> EvidenceStr:
    return EvidenceStr(value=val, evidence_snippet=val, evidence_section="abstract")


def _ev_list(vals: list[str]) -> EvidenceStrList:
    return EvidenceStrList(
        value=vals, evidence_snippet=", ".join(vals), evidence_section="abstract"
    )


def _study(study_type: str = "rct", domain: str = "human_clinical") -> StudyExtraction:
    return StudyExtraction(
        study_type=EvidenceStudyType(
            value=study_type, evidence_snippet=study_type, evidence_section="abstract"
        ),
        evidence_domain=EvidenceDomainType(
            value=domain, evidence_snippet=domain, evidence_section="abstract"
        ),
    )


def _synopsis() -> PaperSynopsis:
    return PaperSynopsis(value="A study.", supporting_evidence_snippets=["A study."])


def _topical(label: str = "high") -> TopicalRelevance:
    return TopicalRelevance(
        label=label, evidence_snippet=label, evidence_section="abstract"
    )


def _base_kwargs():
    return dict(
        paper_synopsis=_synopsis(),
        topical_relevance=_topical(),
        study=_study(),
    )


# ---------------------------------------------------------------------------
# device=None (drug-only paper)
# ---------------------------------------------------------------------------

class TestDeviceNull:
    def test_device_null_accepted(self):
        e = ExtractionResult(**_base_kwargs(), device=None)
        assert e.device is None

    def test_drug_only_extraction_result(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=None,
            drug=DrugExtraction(
                active_ingredient=_ev("ranibizumab"),
                drug_class=_ev("anti-VEGF"),
                route=_ev("intravitreal"),
            ),
        )
        assert e.device is None
        assert e.drug is not None

    def test_normalize_device_null_product_type_drug(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=None,
            drug=DrugExtraction(active_ingredient=_ev("ranibizumab")),
        )
        np = normalize_extraction(e)
        assert np.product_type == "drug"
        assert np.device is None
        assert np.drug is not None

    def test_normalize_device_null_no_device_in_normalized(self):
        e = ExtractionResult(**_base_kwargs(), device=None)
        np = normalize_extraction(e)
        assert np.device is None


# ---------------------------------------------------------------------------
# drug=None (device-only paper)
# ---------------------------------------------------------------------------

class TestDrugNull:
    def test_drug_null_accepted_by_default(self):
        e = ExtractionResult(**_base_kwargs())
        assert e.drug is None

    def test_explicit_drug_null(self):
        e = ExtractionResult(**_base_kwargs(), drug=None)
        assert e.drug is None

    def test_device_only_product_type(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=DeviceExtraction(
                device_category=_ev("intraocular lens"),
                material=_ev("hydrophobic acrylic"),
            ),
            drug=None,
        )
        np = normalize_extraction(e)
        assert np.product_type == "device"
        assert np.drug is None

    def test_normalize_drug_null_no_drug_in_normalized(self):
        e = ExtractionResult(**_base_kwargs(), drug=None)
        np = normalize_extraction(e)
        assert np.drug is None


# ---------------------------------------------------------------------------
# Both device and drug present
# ---------------------------------------------------------------------------

class TestBothPresent:
    def test_both_accepted(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=DeviceExtraction(device_category=_ev("contact lens")),
            drug=DrugExtraction(active_ingredient=_ev("cyclosporine")),
        )
        assert e.device is not None
        assert e.drug is not None

    def test_normalize_both_product_type_both(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=DeviceExtraction(device_category=_ev("contact lens")),
            drug=DrugExtraction(active_ingredient=_ev("cyclosporine")),
        )
        np = normalize_extraction(e)
        assert np.product_type == "both"
        assert np.device is not None
        assert np.drug is not None

    def test_drug_normalized_correctly_when_both_present(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=DeviceExtraction(device_category=_ev("intraocular lens")),
            drug=DrugExtraction(active_ingredient=_ev("ranibizumab")),
        )
        np = normalize_extraction(e)
        assert np.drug is not None
        assert np.drug.active_ingredient_normalized == "ranibizumab"
        assert np.drug.drug_class_normalized == "anti_vegf"

    def test_device_normalized_correctly_when_both_present(self):
        e = ExtractionResult(
            **_base_kwargs(),
            device=DeviceExtraction(device_category=_ev("intraocular lens")),
            drug=DrugExtraction(active_ingredient=_ev("ranibizumab")),
        )
        np = normalize_extraction(e)
        assert np.device is not None
        assert np.device.device_category_normalized == "intraocular_lens"


# ---------------------------------------------------------------------------
# Neither device nor drug (unknown/non-product paper)
# ---------------------------------------------------------------------------

class TestBothNull:
    def test_neither_device_nor_drug(self):
        e = ExtractionResult(**_base_kwargs(), device=None, drug=None)
        np = normalize_extraction(e)
        assert np.product_type == "unknown"
        assert np.device is None
        assert np.drug is None


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_extra_field_on_extraction_result_rejected(self):
        with pytest.raises(ValidationError):
            ExtractionResult(
                **_base_kwargs(),
                unknown_extra_field="should fail",
            )

    def test_extra_field_on_drug_extraction_rejected(self):
        with pytest.raises(ValidationError):
            DrugExtraction(
                active_ingredient=_ev("ranibizumab"),
                unknown_extra="bad",
            )

    def test_extra_field_on_device_extraction_rejected(self):
        with pytest.raises(ValidationError):
            DeviceExtraction(
                device_category=_ev("IOL"),
                unknown_extra="bad",
            )

    def test_invalid_study_type_rejected(self):
        with pytest.raises(ValidationError):
            ExtractionResult(
                **_base_kwargs(),
                study=StudyExtraction(
                    study_type=EvidenceStudyType(
                        value="not_a_real_study_type",
                        evidence_snippet="x",
                        evidence_section="abstract",
                    ),
                    evidence_domain=EvidenceDomainType(
                        value="human_clinical",
                        evidence_snippet="x",
                        evidence_section="abstract",
                    ),
                ),
            )

    def test_missing_required_study_type_rejected(self):
        with pytest.raises(ValidationError):
            StudyExtraction(
                evidence_domain=EvidenceDomainType(
                    value="human_clinical",
                    evidence_snippet="x",
                    evidence_section="abstract",
                ),
            )


# ---------------------------------------------------------------------------
# Brand vs direct alias confidence
# ---------------------------------------------------------------------------

class TestBrandConfidenceVsDirectAlias:
    def test_direct_alias_confidence_higher_than_brand(self):
        direct = normalize_material("hydrophobic acrylic")
        brand = normalize_material("AcrySof")
        assert direct.confidence > brand.confidence

    def test_direct_alias_confidence_is_095(self):
        r = normalize_material("hydrophobic acrylic")
        assert r.confidence == pytest.approx(0.95)

    def test_brand_confidence_is_060(self):
        r = normalize_material("Tecnis")
        assert r.confidence == pytest.approx(0.60)

    def test_brand_gives_correct_subtype(self):
        r = normalize_material("AcrySof Natural")
        assert r.subtype == "hydrophobic_acrylic"

    def test_direct_wins_when_both_in_text(self):
        r = normalize_material("hydrophobic acrylic AcrySof lens")
        assert r.confidence == pytest.approx(0.95), (
            "Direct alias should take priority over brand hint"
        )
