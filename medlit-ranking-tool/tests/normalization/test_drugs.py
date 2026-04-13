"""Tests for ophthalmology drug normalization."""

import pytest

from app.normalization.drugs import normalize_drug
from app.normalization.registry import NormalizationMethod


class TestIngredientNormalization:
    def test_ranibizumab_generic(self):
        r = normalize_drug("ranibizumab")
        assert r.active_ingredient_normalized == "ranibizumab"
        assert r.drug_class_normalized == "anti_vegf"
        assert r.confidence == pytest.approx(0.95)
        assert r.method == NormalizationMethod.DICTIONARY

    def test_lucentis_brand(self):
        r = normalize_drug("Lucentis")
        assert r.active_ingredient_normalized == "ranibizumab"
        assert r.drug_class_normalized == "anti_vegf"

    def test_aflibercept(self):
        r = normalize_drug("aflibercept")
        assert r.active_ingredient_normalized == "aflibercept"
        assert r.drug_class_normalized == "anti_vegf"

    def test_eylea_brand(self):
        r = normalize_drug("Eylea")
        assert r.active_ingredient_normalized == "aflibercept"

    def test_bevacizumab(self):
        r = normalize_drug("bevacizumab")
        assert r.active_ingredient_normalized == "bevacizumab"
        assert r.drug_class_normalized == "anti_vegf"

    def test_avastin_off_label(self):
        r = normalize_drug("Avastin")
        assert r.active_ingredient_normalized == "bevacizumab"

    def test_faricimab(self):
        r = normalize_drug("faricimab")
        assert r.active_ingredient_normalized == "faricimab"

    def test_dexamethasone(self):
        r = normalize_drug("dexamethasone")
        assert r.active_ingredient_normalized == "dexamethasone"
        assert r.drug_class_normalized == "corticosteroid"

    def test_ozurdex_brand(self):
        r = normalize_drug("Ozurdex")
        assert r.active_ingredient_normalized == "dexamethasone"
        assert r.drug_class_normalized == "corticosteroid"

    def test_latanoprost_prostaglandin(self):
        r = normalize_drug("latanoprost")
        assert r.active_ingredient_normalized == "latanoprost"
        assert r.drug_class_normalized == "prostaglandin_analog"

    def test_timolol_beta_blocker(self):
        r = normalize_drug("timolol")
        assert r.drug_class_normalized == "beta_blocker"

    def test_dorzolamide_cai(self):
        r = normalize_drug("dorzolamide")
        assert r.drug_class_normalized == "carbonic_anhydrase_inhibitor"

    def test_cyclosporine_immunomodulator(self):
        r = normalize_drug("cyclosporine")
        assert r.drug_class_normalized == "immunomodulator"

    def test_restasis_brand(self):
        r = normalize_drug("Restasis")
        assert r.active_ingredient_normalized == "cyclosporine"

    def test_atropine_mydriatic(self):
        r = normalize_drug("atropine")
        assert r.drug_class_normalized == "mydriatic_cycloplegic"

    def test_moxifloxacin_antibiotic(self):
        r = normalize_drug("moxifloxacin")
        assert r.drug_class_normalized == "antibiotic"

    def test_case_insensitive(self):
        r = normalize_drug("RANIBIZUMAB")
        assert r.active_ingredient_normalized == "ranibizumab"

    def test_case_insensitive_brand(self):
        r = normalize_drug("LUCENTIS")
        assert r.active_ingredient_normalized == "ranibizumab"


class TestRouteDetection:
    def test_intravitreal_route(self):
        r = normalize_drug("ranibizumab", "intravitreal injection")
        assert r.route_normalized == "intravitreal"

    def test_topical_route(self):
        r = normalize_drug("timolol", "eye drop topical")
        assert r.route_normalized == "topical"

    def test_implant_route(self):
        r = normalize_drug("dexamethasone", "sustained release implant")
        assert r.route_normalized == "implant"

    def test_subconjunctival_route(self):
        r = normalize_drug("triamcinolone", "subconjunctival injection")
        assert r.route_normalized == "subconjunctival"

    def test_oral_route(self):
        r = normalize_drug("acetazolamide", "oral systemic")
        assert r.route_normalized == "oral"

    def test_no_route_context(self):
        r = normalize_drug("ranibizumab")
        assert r.route_normalized is None


class TestFormulationFeatures:
    def test_preservative_free(self):
        r = normalize_drug("timolol", "preservative-free formulation")
        assert "preservative_free" in r.formulation_features_normalized

    def test_extended_release(self):
        r = normalize_drug("dexamethasone", "sustained release implant")
        assert "extended_release" in r.formulation_features_normalized


class TestUnknownDrug:
    def test_unknown_returns_null_normalized(self):
        r = normalize_drug("some novel compound XY-123")
        assert r.active_ingredient_normalized is None
        assert r.drug_class_normalized is None
        assert r.confidence == pytest.approx(0.0)
        assert r.method == NormalizationMethod.UNKNOWN

    def test_raw_name_preserved(self):
        r = normalize_drug("unknown drug ABC")
        assert r.raw_name == "unknown drug ABC"
