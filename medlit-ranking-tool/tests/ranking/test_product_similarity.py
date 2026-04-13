"""Tests for the product similarity scorer (ranking_spec §2.2).

All tests work on NormalizedProduct inputs; normalization is done
via fixtures (precomputed, not inside the scorer).
"""

import pytest

from app.models.normalized import (
    NormalizedDevice,
    NormalizedDrug,
    NormalizedMaterial,
    NormalizedProduct,
)
from app.models.search import SUBMISSION_PRESETS, TargetProductProfile
from app.normalization.registry import NormalizationMethod
from app.ranking.product_similarity import (
    score_feature_overlap,
    score_indication_similarity,
    score_material_similarity,
    score_product_similarity,
    score_drug_similarity,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _norm_device(
    category: str | None = None,
    material_subtype: str | None = None,
    material_family: str | None = None,
    material_features: list[str] | None = None,
    indications: list[str] | None = None,
    anatomical_site: str | None = None,
    product_name: str | None = None,
    manufacturer: str | None = None,
    key_features: list[str] | None = None,
    intended_use_normalized: str | None = None,
    energy_source_normalized: str | None = None,
    device_class: str | None = None,
    sterilization_normalized: str | None = None,
) -> NormalizedDevice:
    mat = None
    if material_subtype or material_family:
        mat = NormalizedMaterial(
            raw="raw_material",
            family=material_family,
            subtype=material_subtype,
            features=material_features or [],
            confidence=0.95,
            method=NormalizationMethod.DICTIONARY,
        )
    return NormalizedDevice(
        device_category_normalized=category,
        material=mat,
        indications_normalized=indications or [],
        anatomical_site_normalized=anatomical_site,
        product_name_raw=product_name,
        manufacturer_raw=manufacturer,
        key_features_normalized=key_features or [],
        intended_use_normalized=intended_use_normalized,
        energy_source_normalized=energy_source_normalized,
        device_class=device_class,
        sterilization_normalized=sterilization_normalized,
        confidence=0.9,
        method=NormalizationMethod.DICTIONARY,
    )


def _norm_drug(
    ingredient: str | None = None,
    drug_class: str | None = None,
    route: str | None = None,
    features: list[str] | None = None,
    product_name: str | None = None,
) -> NormalizedDrug:
    return NormalizedDrug(
        active_ingredient_normalized=ingredient,
        drug_class_normalized=drug_class,
        route_normalized=route,
        formulation_features_normalized=features or [],
        product_name_raw=product_name,
        confidence=0.95 if ingredient else 0.0,
        method=NormalizationMethod.DICTIONARY if ingredient else NormalizationMethod.UNKNOWN,
    )


def _product_device(device: NormalizedDevice) -> NormalizedProduct:
    return NormalizedProduct(device=device, product_type="device")


def _product_drug(drug: NormalizedDrug) -> NormalizedProduct:
    return NormalizedProduct(drug=drug, product_type="drug")


# ---------------------------------------------------------------------------
# score_material_similarity
# ---------------------------------------------------------------------------

class TestMaterialSimilarity:
    def test_exact_subtype_match(self):
        mat = NormalizedMaterial(
            raw="hydrophobic acrylic",
            family="acrylic",
            subtype="hydrophobic_acrylic",
            features=[],
            confidence=0.95,
            method=NormalizationMethod.DICTIONARY,
        )
        assert score_material_similarity(mat, "acrylic", "hydrophobic_acrylic") == pytest.approx(1.0)

    def test_same_family_different_subtype(self):
        mat = NormalizedMaterial(
            raw="hydrophilic acrylic",
            family="acrylic",
            subtype="hydrophilic_acrylic",
            features=[],
            confidence=0.95,
            method=NormalizationMethod.DICTIONARY,
        )
        assert score_material_similarity(mat, "acrylic", "hydrophobic_acrylic") == pytest.approx(0.5)

    def test_different_family(self):
        mat = NormalizedMaterial(
            raw="silicone",
            family="silicone",
            subtype="silicone",
            features=[],
            confidence=0.95,
            method=NormalizationMethod.DICTIONARY,
        )
        assert score_material_similarity(mat, "acrylic", "hydrophobic_acrylic") == pytest.approx(0.0)

    def test_unknown_material(self):
        mat = NormalizedMaterial(
            raw="unknown material",
            family=None,
            subtype=None,
            features=[],
            confidence=0.0,
            method=NormalizationMethod.UNKNOWN,
        )
        assert score_material_similarity(mat, "acrylic", "hydrophobic_acrylic") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# score_drug_similarity
# ---------------------------------------------------------------------------

class TestDrugSimilarity:
    def test_exact_ingredient_match(self):
        drug = _norm_drug(ingredient="ranibizumab", drug_class="anti_vegf")
        ing_s, cls_s = score_drug_similarity(drug, "ranibizumab", "anti_vegf")
        assert ing_s == pytest.approx(1.0)
        assert cls_s == pytest.approx(1.0)

    def test_same_class_different_ingredient(self):
        drug = _norm_drug(ingredient="bevacizumab", drug_class="anti_vegf")
        ing_s, cls_s = score_drug_similarity(drug, "ranibizumab", "anti_vegf")
        assert ing_s == pytest.approx(0.0)
        assert cls_s == pytest.approx(1.0)

    def test_different_class(self):
        drug = _norm_drug(ingredient="dexamethasone", drug_class="corticosteroid")
        ing_s, cls_s = score_drug_similarity(drug, "ranibizumab", "anti_vegf")
        assert ing_s == pytest.approx(0.0)
        assert cls_s == pytest.approx(0.0)

    def test_unknown_drug_no_score(self):
        drug = _norm_drug()
        ing_s, cls_s = score_drug_similarity(drug, "ranibizumab", "anti_vegf")
        assert ing_s == pytest.approx(0.0)
        assert cls_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# score_feature_overlap
# ---------------------------------------------------------------------------

class TestFeatureOverlap:
    def test_full_overlap(self):
        assert score_feature_overlap(["uv_filter", "aspheric"], ["uv_filter", "aspheric"]) == pytest.approx(1.0)

    def test_partial_overlap(self):
        result = score_feature_overlap(["uv_filter", "aspheric", "toric"], ["uv_filter", "aspheric"])
        assert 0.0 < result < 1.0

    def test_no_overlap(self):
        assert score_feature_overlap(["toric"], ["aspheric"]) == pytest.approx(0.0)

    def test_empty_lists(self):
        assert score_feature_overlap([], ["aspheric"]) == pytest.approx(0.0)
        assert score_feature_overlap(["aspheric"], []) == pytest.approx(0.0)

    def test_case_insensitive(self):
        assert score_feature_overlap(["UV_Filter"], ["uv_filter"]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# score_indication_similarity
# ---------------------------------------------------------------------------

class TestIndicationSimilarity:
    def test_exact_match(self):
        assert score_indication_similarity(["cataract"], ["cataract"]) == pytest.approx(1.0)

    def test_partial_match(self):
        result = score_indication_similarity(["cataract", "glaucoma"], ["cataract"])
        assert 0.0 < result < 1.0

    def test_no_match(self):
        assert score_indication_similarity(["glaucoma"], ["cataract"]) == pytest.approx(0.0)

    def test_empty(self):
        assert score_indication_similarity([], ["cataract"]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# score_product_similarity — device mode
# ---------------------------------------------------------------------------

class TestDeviceScoring:
    def test_perfect_device_match(self):
        device = _norm_device(
            category="intraocular_lens",
            material_subtype="hydrophobic_acrylic",
            material_family="acrylic",
            material_features=["uv_filter", "aspheric"],
            indications=["cataract"],
            anatomical_site="lens_capsule",
        )
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            material_subtype="hydrophobic_acrylic",
            material_family="acrylic",
            material_features=["uv_filter", "aspheric"],
            indications=["cataract"],
            anatomical_site="lens_capsule",
        )
        score, breakdown = score_product_similarity(_product_device(device), target)
        assert score > 0.8
        assert breakdown["signals"]["device_category"] == pytest.approx(1.0)
        assert breakdown["signals"]["material_subtype"] == pytest.approx(1.0)

    def test_category_mismatch(self):
        device = _norm_device(category="contact_lens")
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
        )
        score, breakdown = score_product_similarity(_product_device(device), target)
        assert breakdown["signals"]["device_category"] == pytest.approx(0.0)

    def test_same_family_different_subtype_gives_medium(self):
        device = _norm_device(
            category="intraocular_lens",
            material_subtype="hydrophilic_acrylic",
            material_family="acrylic",
        )
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            material_subtype="hydrophobic_acrylic",
            material_family="acrylic",
        )
        score, breakdown = score_product_similarity(_product_device(device), target)
        assert breakdown["signals"]["material_subtype"] == pytest.approx(0.5)

    def test_no_matching_fields_returns_zero(self):
        device = _norm_device()
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
        )
        score, breakdown = score_product_similarity(_product_device(device), target)
        assert score == pytest.approx(0.0)
        assert "note" in breakdown

    def test_weight_renormalization(self):
        device = _norm_device(category="intraocular_lens")
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
        )
        score, breakdown = score_product_similarity(_product_device(device), target)
        assert abs(sum(breakdown["weights"].values()) - 1.0) < 0.001
        assert score == pytest.approx(1.0)

    def test_deterministic(self):
        device = _norm_device(
            category="intraocular_lens",
            indications=["cataract"],
        )
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            indications=["cataract"],
        )
        np = _product_device(device)
        s1, _ = score_product_similarity(np, target)
        s2, _ = score_product_similarity(np, target)
        assert s1 == s2


# ---------------------------------------------------------------------------
# score_product_similarity — drug mode
# ---------------------------------------------------------------------------

class TestDrugScoring:
    def test_exact_ingredient_match_scores_high(self):
        drug = _norm_drug(ingredient="ranibizumab", drug_class="anti_vegf", route="intravitreal")
        target = TargetProductProfile(
            target_type="drug",
            active_ingredient="ranibizumab",
            drug_class="anti_vegf",
            route="intravitreal",
        )
        score, breakdown = score_product_similarity(_product_drug(drug), target)
        assert score > 0.7
        assert breakdown["signals"]["drug_ingredient"] == pytest.approx(1.0)

    def test_same_class_different_ingredient_scores_medium(self):
        drug = _norm_drug(ingredient="bevacizumab", drug_class="anti_vegf")
        target = TargetProductProfile(
            target_type="drug",
            active_ingredient="ranibizumab",
            drug_class="anti_vegf",
        )
        score, breakdown = score_product_similarity(_product_drug(drug), target)
        assert breakdown["signals"]["drug_ingredient"] == pytest.approx(0.0)
        assert breakdown["signals"]["drug_class"] == pytest.approx(1.0)

    def test_unknown_drug_returns_zero(self):
        drug = _norm_drug()
        target = TargetProductProfile(
            target_type="drug",
            active_ingredient="ranibizumab",
        )
        score, _ = score_product_similarity(_product_drug(drug), target)
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Null device / drug on NormalizedProduct
# ---------------------------------------------------------------------------

class TestNullNormalized:
    def test_device_target_but_no_device_in_normalized(self):
        np = NormalizedProduct(device=None, drug=None, product_type="unknown")
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
        )
        score, breakdown = score_product_similarity(np, target)
        assert score == pytest.approx(0.0)
        assert "note" in breakdown

    def test_drug_target_but_no_drug_in_normalized(self):
        np = NormalizedProduct(device=None, drug=None, product_type="unknown")
        target = TargetProductProfile(
            target_type="drug",
            active_ingredient="ranibizumab",
        )
        score, breakdown = score_product_similarity(np, target)
        assert score == pytest.approx(0.0)
        assert "note" in breakdown


# ---------------------------------------------------------------------------
# Integration: fixtures from conftest
# ---------------------------------------------------------------------------

class TestIntendedUseScoring:
    def test_exact_intended_use_match_scores_1(self):
        device = _norm_device(
            category="intraocular_lens",
            intended_use_normalized="cataract_surgery",
        )
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            intended_use="cataract_surgery",
        )
        score, breakdown = score_product_similarity(_product_device(device), target)
        assert breakdown["signals"]["intended_use"] == pytest.approx(1.0)
        assert score > 0.0

    def test_partial_intended_use_match_scores_06(self):
        device = _norm_device(
            category="intraocular_lens",
            intended_use_normalized="cataract_surgery",
        )
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            intended_use="cataract",
        )
        _, breakdown = score_product_similarity(_product_device(device), target)
        assert breakdown["signals"]["intended_use"] == pytest.approx(0.6)

    def test_missing_intended_use_excluded(self):
        device = _norm_device(
            category="intraocular_lens",
            intended_use_normalized=None,
        )
        target = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            intended_use="cataract_surgery",
        )
        _, breakdown = score_product_similarity(_product_device(device), target)
        assert "intended_use" not in breakdown["signals"]


class TestSubmissionPresetWeights:
    def test_510k_device_weights_sum_to_1(self):
        w = SUBMISSION_PRESETS["510k"]["device_sub_weights"]
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_pma_device_weights_sum_to_1(self):
        w = SUBMISSION_PRESETS["pma"]["device_sub_weights"]
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_denovo_device_weights_sum_to_1(self):
        w = SUBMISSION_PRESETS["de_novo"]["device_sub_weights"]
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_510k_boosts_intended_use(self):
        d510 = SUBMISSION_PRESETS["510k"]["device_sub_weights"]["intended_use"]
        default = 0.15  # _DEFAULT_DEVICE_WEIGHTS
        assert d510 > default

    def test_pma_boosts_evidence_quality(self):
        pma_e = SUBMISSION_PRESETS["pma"]["composite"]["E"]
        default_e = 0.20
        assert pma_e > default_e


class TestWithConftest:
    def test_iol_fixture_scores_high(
        self, iol_normalized: NormalizedProduct, iol_target: TargetProductProfile
    ):
        score, _ = score_product_similarity(iol_normalized, iol_target)
        assert score > 0.6

    def test_avegf_fixture_scores_high(
        self, avegf_normalized: NormalizedProduct, avegf_target: TargetProductProfile
    ):
        score, breakdown = score_product_similarity(avegf_normalized, avegf_target)
        assert score > 0.5

    def test_legacy_extraction_device_none_graceful(
        self, normalized: NormalizedProduct, target_product: TargetProductProfile
    ):
        score, _ = score_product_similarity(normalized, target_product)
        assert 0.0 <= score <= 1.0
