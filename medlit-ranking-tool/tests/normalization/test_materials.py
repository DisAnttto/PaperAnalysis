"""Tests for ophthalmology material normalization."""

import pytest

from app.normalization.materials import (
    MATERIAL_BRAND_HINTS,
    MATERIAL_DIRECT_ALIASES,
    MATERIAL_FEATURE_KEYWORDS,
    normalize_material,
)
from app.normalization.registry import NormalizationMethod


class TestDirectAliases:
    def test_exact_match_hydrophobic_acrylic(self):
        r = normalize_material("hydrophobic acrylic")
        assert r.subtype == "hydrophobic_acrylic"
        assert r.family == "acrylic"
        assert r.confidence == pytest.approx(0.95)
        assert r.method == NormalizationMethod.DICTIONARY

    def test_exact_match_hydrophilic_acrylic(self):
        r = normalize_material("hydrophilic acrylic")
        assert r.subtype == "hydrophilic_acrylic"
        assert r.family == "acrylic"

    def test_exact_match_silicone(self):
        r = normalize_material("silicone")
        assert r.subtype == "silicone"
        assert r.family == "silicone"
        assert r.confidence == pytest.approx(0.95)

    def test_exact_match_pmma(self):
        r = normalize_material("PMMA")
        assert r.subtype == "pmma"
        assert r.family == "pmma"

    def test_exact_match_collamer(self):
        r = normalize_material("collamer")
        assert r.subtype == "collamer"
        assert r.family == "collamer"

    def test_exact_match_hydrogel(self):
        r = normalize_material("hydrogel")
        assert r.subtype == "hydrogel"
        assert r.family == "hydrogel"

    def test_case_insensitive(self):
        r = normalize_material("HYDROPHOBIC ACRYLIC")
        assert r.subtype == "hydrophobic_acrylic"

    def test_substring_match(self):
        r = normalize_material("made from hydrophobic acrylic material")
        assert r.subtype == "hydrophobic_acrylic"
        assert r.confidence == pytest.approx(0.95)

    def test_poly_methyl_methacrylate(self):
        r = normalize_material("poly(methyl methacrylate)")
        assert r.subtype == "pmma"

    def test_pmma_full_name(self):
        r = normalize_material("polymethylmethacrylate lens")
        assert r.subtype == "pmma"


class TestBrandHints:
    """Brand hints must return lower confidence than direct aliases."""

    def test_acrysof_brand_confidence(self):
        r = normalize_material("AcrySof")
        assert r.subtype == "hydrophobic_acrylic"
        assert r.confidence == pytest.approx(0.60)
        assert r.method == NormalizationMethod.DICTIONARY

    def test_tecnis_brand_confidence(self):
        r = normalize_material("Tecnis lens")
        assert r.confidence == pytest.approx(0.60)
        assert r.subtype == "hydrophobic_acrylic"

    def test_envista_brand_confidence(self):
        r = normalize_material("enVista IOL")
        assert r.confidence == pytest.approx(0.60)
        assert r.subtype == "hydrophobic_acrylic"

    def test_brand_only_used_when_no_direct_match(self):
        r_direct = normalize_material("hydrophobic acrylic acrysof")
        assert r_direct.confidence == pytest.approx(0.95), (
            "Direct alias should win over brand hint when both match"
        )

    def test_akreos_hydrophilic(self):
        r = normalize_material("Akreos IOL")
        assert r.subtype == "hydrophilic_acrylic"
        assert r.confidence == pytest.approx(0.60)

    def test_visian_icl_collamer(self):
        r = normalize_material("Visian ICL implant")
        assert r.subtype == "collamer"
        assert r.confidence == pytest.approx(0.60)


class TestFeatureDetection:
    def test_uv_filter_detected(self):
        r = normalize_material("hydrophobic acrylic with UV filter")
        assert "uv_filter" in r.features

    def test_blue_light_filter(self):
        r = normalize_material("hydrophobic acrylic blue light filter IOL")
        assert "blue_light_filter" in r.features

    def test_toric_feature(self):
        r = normalize_material("toric hydrophobic acrylic")
        assert "toric" in r.features

    def test_multifocal_feature(self):
        r = normalize_material("multifocal diffractive acrylic")
        assert "multifocal" in r.features

    def test_aspheric_feature(self):
        r = normalize_material("aspheric silicone IOL")
        assert "aspheric" in r.features
        assert r.subtype == "silicone"

    def test_features_without_material_match(self):
        r = normalize_material("toric monofocal lens")
        assert "toric" in r.features
        assert "monofocal" in r.features

    def test_multiple_features(self):
        r = normalize_material("hydrophobic acrylic toric UV filter aspheric IOL")
        assert "toric" in r.features
        assert "uv_filter" in r.features
        assert "aspheric" in r.features

    def test_preservative_free(self):
        r = normalize_material("preservative-free hydrogel contact lens")
        assert "preservative_free" in r.features

    def test_drug_eluting(self):
        r = normalize_material("drug-eluting contact lens")
        assert "drug_eluting" in r.features


class TestUnknownMaterial:
    def test_unknown_returns_null_canonical(self):
        r = normalize_material("unknown novel polymer X")
        assert r.family is None
        assert r.subtype is None
        assert r.confidence == pytest.approx(0.0)
        assert r.method == NormalizationMethod.UNKNOWN

    def test_raw_preserved(self):
        raw = "some exotic biomaterial"
        r = normalize_material(raw)
        assert r.raw == raw

    def test_empty_string(self):
        r = normalize_material("")
        assert r.family is None
        assert r.subtype is None
