"""Unit tests for the query rewrite generator."""

import pytest

from app.models.search import TargetProductProfile
from app.services.rewrite_generator import (
    RewriteSet,
    _expand_synonyms,
    generate_rewrites,
)


class TestSynonymExpansion:
    def test_known_synonym(self):
        syns = _expand_synonyms("IOP")
        assert "intraocular pressure" in syns

    def test_unknown_term_returns_self(self):
        assert _expand_synonyms("xyzzy") == ["xyzzy"]

    def test_case_insensitive(self):
        assert _expand_synonyms("BCVA") == _expand_synonyms("bcva")


class TestGenerateRewrites:
    def test_basic_query_produces_all_sources(self):
        rw = generate_rewrites("IOP after cataract surgery")
        assert len(rw.pubmed) >= 1
        assert len(rw.openfda_device) >= 1
        assert len(rw.openfda_drug) >= 1
        assert len(rw.clinical_trials) >= 1
        assert len(rw.dailymed) >= 1
        assert len(rw.access_gudid) >= 1

    def test_pubmed_synonym_expansion(self):
        rw = generate_rewrites("IOP after phaco")
        has_synonym = any(r.variant == "synonym_expanded" for r in rw.pubmed)
        assert has_synonym

    def test_with_target_product(self):
        tp = TargetProductProfile(
            active_ingredient="faricimab",
            product_name="VABYSMO",
            indications=["nAMD", "DME"],
            device_category="",
        )
        rw = generate_rewrites("intravitreal injection efficacy", tp)
        assert any("faricimab" in r.query_text for r in rw.openfda_drug)
        assert any("faricimab" in r.query_text for r in rw.dailymed)
        assert any("VABYSMO" in r.query_text for r in rw.access_gudid)

    def test_device_category_rewrites(self):
        tp = TargetProductProfile(device_category="intraocular_lens")
        rw = generate_rewrites("IOL performance", tp)
        assert any("intraocular lens" in r.query_text for r in rw.openfda_device)

    def test_clinical_trials_structured_rewrite(self):
        tp = TargetProductProfile(
            active_ingredient="dexamethasone",
            indications=["DME"],
        )
        rw = generate_rewrites("steroid implant outcomes", tp)
        structured = [r for r in rw.clinical_trials if r.variant == "structured"]
        assert len(structured) >= 1
        assert "dexamethasone" in structured[0].query_text

    def test_no_profile_uses_free_text(self):
        rw = generate_rewrites("diabetes retinopathy screening")
        for r in rw.openfda_device:
            assert r.variant == "free_text"
        for r in rw.openfda_drug:
            assert r.variant == "free_text"
