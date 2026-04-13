"""Tests for ophthalmology anatomical site and indication normalization."""

import pytest

from app.normalization.anatomy import (
    normalize_anatomical_site,
    normalize_indication,
    normalize_indications,
)
from app.normalization.registry import NormalizationMethod


class TestAnatomicalSiteNormalization:
    def test_cornea(self):
        r = normalize_anatomical_site("cornea")
        assert r.canonical == "cornea"
        assert r.confidence == pytest.approx(0.95)

    def test_retina(self):
        r = normalize_anatomical_site("retina")
        assert r.canonical == "retina"

    def test_macula(self):
        r = normalize_anatomical_site("macula")
        assert r.canonical == "macula"

    def test_vitreous(self):
        r = normalize_anatomical_site("vitreous")
        assert r.canonical == "vitreous"

    def test_anterior_segment(self):
        r = normalize_anatomical_site("anterior segment")
        assert r.canonical == "anterior_segment"

    def test_trabecular_meshwork(self):
        r = normalize_anatomical_site("trabecular meshwork")
        assert r.canonical == "trabecular_meshwork"

    def test_lens_capsule(self):
        r = normalize_anatomical_site("lens capsule")
        assert r.canonical == "lens_capsule"

    def test_optic_nerve(self):
        r = normalize_anatomical_site("optic nerve")
        assert r.canonical == "optic_nerve"

    def test_ocular_surface(self):
        r = normalize_anatomical_site("ocular surface")
        assert r.canonical == "ocular_surface"

    def test_case_insensitive(self):
        r = normalize_anatomical_site("CORNEA")
        assert r.canonical == "cornea"

    def test_substring_match(self):
        r = normalize_anatomical_site("retinal surface")
        assert r.canonical == "retina"

    def test_unknown_site(self):
        r = normalize_anatomical_site("some non-ocular location")
        assert r.canonical is None
        assert r.method == NormalizationMethod.UNKNOWN

    def test_fovea_maps_to_macula(self):
        r = normalize_anatomical_site("fovea")
        assert r.canonical == "macula"

    def test_schlemms_canal(self):
        r = normalize_anatomical_site("schlemm's canal")
        assert r.canonical == "trabecular_meshwork"


class TestIndicationNormalization:
    def test_cataract(self):
        r = normalize_indication("cataract")
        assert r.canonical == "cataract"

    def test_phacoemulsification(self):
        r = normalize_indication("phacoemulsification")
        assert r.canonical == "cataract"

    def test_glaucoma(self):
        r = normalize_indication("glaucoma")
        assert r.canonical == "glaucoma"

    def test_poag(self):
        r = normalize_indication("POAG")
        assert r.canonical == "glaucoma"

    def test_dry_eye(self):
        r = normalize_indication("dry eye disease")
        assert r.canonical == "dry_eye"

    def test_amd(self):
        r = normalize_indication("AMD")
        assert r.canonical == "macular_degeneration"

    def test_wet_amd(self):
        r = normalize_indication("wet AMD")
        assert r.canonical == "macular_degeneration"

    def test_dme(self):
        r = normalize_indication("diabetic macular edema")
        assert r.canonical == "diabetic_macular_edema"

    def test_dme_abbreviation(self):
        r = normalize_indication("DME")
        assert r.canonical == "diabetic_macular_edema"

    def test_diabetic_retinopathy(self):
        r = normalize_indication("diabetic retinopathy")
        assert r.canonical == "diabetic_retinopathy"

    def test_keratoconus(self):
        r = normalize_indication("keratoconus")
        assert r.canonical == "keratoconus"

    def test_uveitis(self):
        r = normalize_indication("uveitis")
        assert r.canonical == "uveitis"

    def test_retinal_detachment(self):
        r = normalize_indication("retinal detachment")
        assert r.canonical == "retinal_detachment"

    def test_myopia(self):
        r = normalize_indication("myopia")
        assert r.canonical == "myopia"

    def test_unknown_indication(self):
        r = normalize_indication("unknown rare condition")
        assert r.canonical is None
        assert r.method == NormalizationMethod.UNKNOWN


class TestNormalizeIndications:
    def test_multiple_indications(self):
        result = normalize_indications(["cataract", "glaucoma"])
        assert "cataract" in result.canonical
        assert "glaucoma" in result.canonical
        assert result.confidence > 0

    def test_partial_match_list(self):
        result = normalize_indications(["cataract", "some unknown condition"])
        assert "cataract" in result.canonical
        assert len(result.canonical) == 1

    def test_empty_list(self):
        result = normalize_indications([])
        assert result.canonical == []
        assert result.confidence == pytest.approx(0.0)

    def test_all_unknown(self):
        result = normalize_indications(["xyz abc", "foo bar"])
        assert result.canonical == []
        assert result.method == NormalizationMethod.UNKNOWN

    def test_raw_list_preserved(self):
        raw = ["cataract", "glaucoma"]
        result = normalize_indications(raw)
        assert result.raw == raw
