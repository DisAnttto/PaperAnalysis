"""Integration tests — demo mode fixture consistency and normalization."""

import pytest

from app.demo.fixtures import (
    get_all_demo_triples,
    get_demo_extraction,
    get_demo_normalized,
    get_demo_papers,
)
from app.models.extraction import ExtractionResult
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper


class TestDemoFixtures:
    def test_six_papers_loaded(self):
        papers = get_demo_papers()
        assert len(papers) == 6

    def test_all_papers_have_pmid(self):
        for p in get_demo_papers():
            assert p.pmid and (p.pmid.startswith("DEMO") or p.pmid.isdigit())

    def test_all_papers_have_title(self):
        for p in get_demo_papers():
            assert p.title

    def test_all_papers_have_abstract(self):
        for p in get_demo_papers():
            assert p.abstract

    def test_all_papers_have_extraction(self):
        for p in get_demo_papers():
            ext = get_demo_extraction(p.pmid)
            assert ext is not None
            assert isinstance(ext, ExtractionResult)

    def test_all_extractions_validate(self):
        """Pydantic validation passes — no model construction errors."""
        for p in get_demo_papers():
            ext = get_demo_extraction(p.pmid)
            dumped = ext.model_dump()
            ExtractionResult.model_validate(dumped)

    def test_all_papers_have_normalized(self):
        for p in get_demo_papers():
            norm = get_demo_normalized(p.pmid)
            assert norm is not None
            assert isinstance(norm, NormalizedProduct)

    def test_normalized_product_type_is_valid(self):
        for p in get_demo_papers():
            norm = get_demo_normalized(p.pmid)
            assert norm.product_type in ("device", "drug", "both", "unknown")

    def test_demo001_is_device(self):
        norm = get_demo_normalized("DEMO001")
        assert norm.product_type == "device"
        assert norm.device is not None

    def test_39350227_is_drug(self):
        norm = get_demo_normalized("39350227")
        assert norm.product_type == "drug"
        assert norm.drug is not None

    def test_demo006_is_both(self):
        """Contact lens / drug-eluting fixture has both device and drug."""
        norm = get_demo_normalized("DEMO006")
        assert norm.product_type == "both"
        assert norm.device is not None
        assert norm.drug is not None

    def test_get_all_triples_count(self):
        triples = get_all_demo_triples()
        assert len(triples) == 6

    def test_triples_types(self):
        for paper, ext, norm in get_all_demo_triples():
            assert isinstance(paper, Paper)
            assert isinstance(ext, ExtractionResult)
            assert isinstance(norm, NormalizedProduct)


class TestNormalizationConsistency:
    """Cross-check normalization results are deterministic and reasonable."""

    def test_demo001_material_normalized(self):
        norm = get_demo_normalized("DEMO001")
        mat = norm.device.material
        assert mat is not None
        assert mat.family == "acrylic"
        assert mat.subtype in ("hydrophobic_acrylic", None)

    def test_39350227_drug_normalized(self):
        norm = get_demo_normalized("39350227")
        drug = norm.drug
        assert drug is not None
        assert drug.active_ingredient_normalized == "faricimab"
        assert drug.drug_class_normalized == "anti_vegf"

    def test_demo005_drug_normalized(self):
        norm = get_demo_normalized("DEMO005")
        drug = norm.drug
        assert drug is not None
        assert drug.active_ingredient_normalized == "dexamethasone"
        assert drug.drug_class_normalized == "corticosteroid"

    def test_normalization_is_deterministic(self):
        from app.normalization import normalize_extraction

        ext = get_demo_extraction("DEMO001")
        n1 = normalize_extraction(ext)
        n2 = normalize_extraction(ext)
        assert n1.model_dump() == n2.model_dump()


class TestDemoRanking:
    """Smoke-test ranking across all fixture combinations."""

    IOL_TARGET = {
        "query": "intraocular lens cataract",
        "target_product": {
            "target_type": "device",
            "device_category": "intraocular_lens",
            "indications": ["cataract"],
        },
    }

    def test_ranking_runs_without_error(self, client):
        r = client.post("/api/v1/search", json=self.IOL_TARGET)
        assert r.status_code == 200

    def test_ranking_all_scores_in_range(self, client):
        data = client.post("/api/v1/search", json=self.IOL_TARGET).json()
        for r in data["results"]:
            for key in (
                "composite_score",
                "relevance_score",
                "product_similarity_score",
                "evidence_quality_score",
            ):
                assert 0.0 <= r[key] <= 1.0, f"{key} out of range: {r[key]}"

    def test_ranking_is_deterministic(self, client):
        r1 = client.post("/api/v1/search", json=self.IOL_TARGET).json()["results"]
        r2 = client.post("/api/v1/search", json=self.IOL_TARGET).json()["results"]
        assert [(r["pmid"], r["composite_score"]) for r in r1] == [
            (r["pmid"], r["composite_score"]) for r in r2
        ]

    def test_drug_query_returns_results(self, client):
        payload = {
            "query": "anti-VEGF intravitreal AMD faricimab",
            "target_product": {
                "target_type": "drug",
                "active_ingredient": "faricimab",
                "drug_class": "anti_vegf",
            },
        }
        data = client.post("/api/v1/search", json=payload).json()
        assert len(data["results"]) >= 1
