"""Unit tests for the rule-based intent router."""

import pytest

from app.models.search import SearchRequest, TargetProductProfile
from app.services.intent_router import (
    ALL_SOURCES,
    QueryIntent,
    classify_intent,
    get_routing,
    route_sources,
)


class TestClassifyIntent:
    def test_efficacy_keywords(self):
        assert classify_intent("faricimab efficacy in nAMD") == QueryIntent.EFFICACY

    def test_safety_keywords(self):
        assert classify_intent("adverse events after cataract surgery") == QueryIntent.SAFETY

    def test_regulatory_keywords(self):
        assert classify_intent("510(k) clearance for IOL device") == QueryIntent.REGULATORY

    def test_guideline_keywords(self):
        assert classify_intent("AAO clinical practice guideline DME") == QueryIntent.GUIDELINES

    def test_general_fallback(self):
        assert classify_intent("intraocular pressure after phaco") == QueryIntent.GENERAL

    def test_submission_type_boosts_regulatory(self):
        intent = classify_intent("device performance", submission_type="510k")
        assert intent == QueryIntent.REGULATORY

    def test_target_product_device_boosts_regulatory(self):
        tp = TargetProductProfile(device_category="IOL")
        intent = classify_intent("lens performance", target_product=tp)
        assert intent == QueryIntent.REGULATORY

    def test_target_product_drug_boosts_efficacy(self):
        tp = TargetProductProfile(active_ingredient="faricimab")
        intent = classify_intent("intravitreal injection outcomes", target_product=tp)
        assert intent == QueryIntent.EFFICACY

    def test_mixed_signals_picks_strongest(self):
        assert classify_intent("510k safety adverse events") == QueryIntent.SAFETY


class TestRouteSources:
    def test_efficacy_excludes_gudid(self):
        decision = route_sources(QueryIntent.EFFICACY, 30)
        assert "AccessGUDID" not in decision.enabled_sources
        assert "PubMed" in decision.enabled_sources
        assert "OpenAlex" in decision.enabled_sources

    def test_safety_includes_all(self):
        decision = route_sources(QueryIntent.SAFETY, 30)
        assert decision.enabled_sources == ALL_SOURCES

    def test_regulatory_includes_all(self):
        decision = route_sources(QueryIntent.REGULATORY, 30)
        assert decision.enabled_sources == ALL_SOURCES

    def test_guidelines_focused(self):
        decision = route_sources(QueryIntent.GUIDELINES, 30)
        assert "PubMed" in decision.enabled_sources
        assert "OpenAlex" in decision.enabled_sources
        assert "openFDA_device" not in decision.enabled_sources

    def test_general_includes_all(self):
        decision = route_sources(QueryIntent.GENERAL, 30)
        assert decision.enabled_sources == ALL_SOURCES

    def test_safety_device_excludes_openfda_drug(self):
        """Drug-label search is noise for a device target; must be suppressed."""
        decision = route_sources(QueryIntent.SAFETY, 30, target_type="device")
        assert "openFDA_drug" not in decision.enabled_sources
        assert "openFDA_device" in decision.enabled_sources
        assert "PubMed" in decision.enabled_sources

    def test_safety_drug_keeps_openfda_drug(self):
        """Drug targets must still search drug labels."""
        decision = route_sources(QueryIntent.SAFETY, 30, target_type="drug")
        assert "openFDA_drug" in decision.enabled_sources

    def test_efficacy_device_excludes_openfda_drug(self):
        decision = route_sources(QueryIntent.EFFICACY, 30, target_type="device")
        assert "openFDA_drug" not in decision.enabled_sources

    def test_general_device_excludes_openfda_drug(self):
        decision = route_sources(QueryIntent.GENERAL, 30, target_type="device")
        assert "openFDA_drug" not in decision.enabled_sources


class TestGetRouting:
    def test_end_to_end(self):
        req = SearchRequest(query="faricimab efficacy nAMD", pool_size=30, max_results=5)
        decision = get_routing(req)
        assert decision.intent == QueryIntent.EFFICACY
        assert "PubMed" in decision.enabled_sources

    def test_device_target_suppresses_drug_labels(self):
        """get_routing must propagate target_type so drug labels are excluded for a device."""
        tp = TargetProductProfile(
            target_type="device",
            device_category="intraocular_lens",
            indications=["cataract"],
        )
        req = SearchRequest(
            query="intraocular pressure postoperative cataract surgery adverse",
            pool_size=30,
            max_results=5,
            target_product=tp,
        )
        decision = get_routing(req)
        assert "openFDA_drug" not in decision.enabled_sources
        assert "openFDA_device" in decision.enabled_sources
