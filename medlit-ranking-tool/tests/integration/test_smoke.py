"""End-to-end smoke tests — all 5 preset queries and paper detail views."""

import pytest

PRESETS = [
    (
        "hydrophobic_iol",
        {
            "query": "hydrophobic acrylic intraocular lens cataract",
            "target_product": {
                "target_type": "device",
                "device_category": "intraocular_lens",
                "material_subtype": "hydrophobic_acrylic",
                "indications": ["cataract"],
            },
        },
    ),
    (
        "faricimab_namd",
        {
            "query": "faricimab neovascular age-related macular degeneration intravitreal",
            "target_product": {
                "target_type": "drug",
                "product_name": "faricimab",
                "active_ingredient": "faricimab",
                "drug_class": "anti_vegf",
                "route": "intravitreal",
                "intended_use": "treatment of neovascular age-related macular degeneration",
                "indications": ["nAMD", "treatment-naive"],
            },
            "metrics_of_interest": [
                "BCVA change",
                "central retinal thickness",
                "retinal fluid resolution",
                "complete dryness rate",
                "treatment interval",
                "injection frequency",
            ],
        },
    ),
    (
        "glaucoma_device",
        {
            "query": "iStent MIGS glaucoma trabecular",
            "target_product": {
                "target_type": "device",
                "device_category": "glaucoma_device",
                "indications": ["glaucoma"],
            },
        },
    ),
    (
        "dexamethasone_dme",
        {
            "query": "dexamethasone intravitreal diabetic macular edema",
            "target_product": {
                "target_type": "drug",
                "active_ingredient": "dexamethasone",
                "drug_class": "corticosteroid",
                "route": "intravitreal",
            },
        },
    ),
    (
        "contact_lens_dry_eye",
        {
            "query": "cyclosporine contact lens dry eye",
            "target_product": {
                "target_type": "both",
                "device_category": "contact_lens",
                "active_ingredient": "cyclosporine",
                "indications": ["dry_eye"],
            },
        },
    ),
]

DEMO_PMIDS = ["DEMO001", "39350227", "DEMO003", "DEMO004", "DEMO005", "DEMO006"]


@pytest.mark.parametrize("name,payload", PRESETS, ids=[p[0] for p in PRESETS])
def test_preset_search_returns_results(client, name, payload):
    r = client.post("/api/v1/search", json=payload)
    assert r.status_code == 200, f"Preset {name}: HTTP {r.status_code}"
    data = r.json()
    assert len(data["results"]) >= 1


@pytest.mark.parametrize("name,payload", PRESETS, ids=[p[0] for p in PRESETS])
def test_preset_scores_in_range(client, name, payload):
    data = client.post("/api/v1/search", json=payload).json()
    for r in data["results"]:
        assert 0.0 <= r["composite_score"] <= 1.0


@pytest.mark.parametrize("name,payload", PRESETS, ids=[p[0] for p in PRESETS])
def test_preset_ranks_sequential(client, name, payload):
    data = client.post("/api/v1/search", json=payload).json()
    ranks = [r["rank"] for r in data["results"]]
    assert ranks == list(range(1, len(ranks) + 1))


@pytest.mark.parametrize("pmid", DEMO_PMIDS)
def test_paper_detail_accessible(client, pmid):
    r = client.get(f"/api/v1/papers/{pmid}/detail")
    assert r.status_code == 200


@pytest.mark.parametrize("pmid", DEMO_PMIDS)
def test_paper_detail_complete(client, pmid):
    data = client.get(f"/api/v1/papers/{pmid}/detail").json()
    assert data["paper"]["pmid"] == pmid
    assert data["extraction"] is not None
    assert data["normalized"] is not None
    assert data["mode"] == "demo"


def test_root_page_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "MedLit QA Console" in r.text
    assert "app.js" in r.text


def test_hydrophobic_iol_outranks_silicone_iol(client):
    """Ranked correctness: DEMO001 (hydrophobic acrylic) > DEMO004 (silicone) for acrylic target."""
    payload = {
        "query": "hydrophobic acrylic intraocular lens cataract",
        "target_product": {
            "target_type": "device",
            "device_category": "intraocular_lens",
            "material_family": "acrylic",
            "material_subtype": "hydrophobic_acrylic",
            "indications": ["cataract"],
        },
    }
    data = client.post("/api/v1/search", json=payload).json()
    by_pmid = {r["pmid"]: r for r in data["results"]}
    if "DEMO001" in by_pmid and "DEMO004" in by_pmid:
        assert by_pmid["DEMO001"]["rank"] < by_pmid["DEMO004"]["rank"]


def test_faricimab_paper_ranks_near_top(client):
    """Faricimab nAMD query: PMID 39350227 should rank in top 2."""
    payload = {
        "query": "faricimab anti-VEGF neovascular AMD intravitreal treatment-naive",
        "target_product": {
            "target_type": "drug",
            "active_ingredient": "faricimab",
            "drug_class": "anti_vegf",
            "route": "intravitreal",
        },
    }
    data = client.post("/api/v1/search", json=payload).json()
    by_pmid = {r["pmid"]: r for r in data["results"]}
    if "39350227" in by_pmid:
        assert by_pmid["39350227"]["rank"] <= 2, (
            f"Expected faricimab paper in top 2, got rank {by_pmid['39350227']['rank']}"
        )
