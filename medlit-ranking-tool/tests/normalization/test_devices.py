"""Tests for ophthalmology device category normalization."""

import pytest

from app.normalization.devices import normalize_device_category
from app.normalization.registry import NormalizationMethod


class TestDeviceCategoryNormalization:
    def test_iol_abbreviation(self):
        r = normalize_device_category("IOL")
        assert r.canonical == "intraocular_lens"
        assert r.confidence == pytest.approx(0.95)
        assert r.method == NormalizationMethod.DICTIONARY

    def test_intraocular_lens_full(self):
        r = normalize_device_category("intraocular lens")
        assert r.canonical == "intraocular_lens"

    def test_multifocal_iol(self):
        r = normalize_device_category("multifocal IOL")
        assert r.canonical == "intraocular_lens"

    def test_toric_iol(self):
        r = normalize_device_category("toric IOL")
        assert r.canonical == "intraocular_lens"

    def test_icl(self):
        r = normalize_device_category("implantable collamer lens")
        assert r.canonical == "intraocular_lens"

    def test_contact_lens(self):
        r = normalize_device_category("contact lens")
        assert r.canonical == "contact_lens"

    def test_scleral_lens(self):
        r = normalize_device_category("scleral lens")
        assert r.canonical == "contact_lens"

    def test_glaucoma_drainage(self):
        r = normalize_device_category("glaucoma drainage device")
        assert r.canonical == "glaucoma_device"

    def test_migs_device(self):
        r = normalize_device_category("MIGS device")
        assert r.canonical == "glaucoma_device"

    def test_istent(self):
        r = normalize_device_category("iStent")
        assert r.canonical == "glaucoma_device"

    def test_retinal_implant(self):
        r = normalize_device_category("retinal implant")
        assert r.canonical == "retinal_device"

    def test_corneal_implant(self):
        r = normalize_device_category("corneal implant")
        assert r.canonical == "corneal_device"

    def test_keratoprosthesis(self):
        r = normalize_device_category("keratoprosthesis")
        assert r.canonical == "corneal_device"

    def test_viscoelastic(self):
        r = normalize_device_category("viscoelastic")
        assert r.canonical == "ophthalmic_viscosurgical_device"

    def test_healon(self):
        r = normalize_device_category("Healon")
        assert r.canonical == "ophthalmic_viscosurgical_device"

    def test_case_insensitive(self):
        r = normalize_device_category("INTRAOCULAR LENS")
        assert r.canonical == "intraocular_lens"

    def test_substring_match(self):
        r = normalize_device_category("hydrophobic acrylic IOL implanted in cataract surgery")
        assert r.canonical == "intraocular_lens"

    def test_unknown_returns_null(self):
        r = normalize_device_category("some unknown ophthalmic thing")
        assert r.canonical is None
        assert r.confidence == pytest.approx(0.0)
        assert r.method == NormalizationMethod.UNKNOWN

    def test_raw_preserved(self):
        raw = "novel ophthalmic implant XYZ"
        r = normalize_device_category(raw)
        assert r.raw == raw
