"""Integration tests — POST /api/v1/search."""

import pytest


IOL_PAYLOAD = {
    "query": "intraocular lens cataract acrylic",
    "target_product": {
        "target_type": "device",
        "device_category": "intraocular_lens",
        "material_subtype": "hydrophobic_acrylic",
        "indications": ["cataract"],
    },
}

ANTIVEGF_PAYLOAD = {
    "query": "faricimab anti-VEGF neovascular AMD intravitreal",
    "target_product": {
        "target_type": "drug",
        "active_ingredient": "faricimab",
        "drug_class": "anti_vegf",
        "route": "intravitreal",
    },
}


def test_search_returns_200(client):
    r = client.post("/api/v1/search", json=IOL_PAYLOAD)
    assert r.status_code == 200


def test_search_response_shape(client):
    data = client.post("/api/v1/search", json=IOL_PAYLOAD).json()
    assert "results" in data
    assert "total" in data
    assert data["mode"] == "demo"
    assert isinstance(data["results"], list)


def test_search_returns_ranked_results(client):
    data = client.post("/api/v1/search", json=IOL_PAYLOAD).json()
    results = data["results"]
    assert len(results) >= 1

    for r in results:
        assert "rank" in r
        assert "composite_score" in r
        assert 0.0 <= r["composite_score"] <= 1.0
        assert 0.0 <= r["relevance_score"] <= 1.0
        assert 0.0 <= r["product_similarity_score"] <= 1.0
        assert 0.0 <= r["evidence_quality_score"] <= 1.0
        assert "evidence_breakdown" in r
        assert r["evidence_breakdown"] is not None
        assert "base_score" in r["evidence_breakdown"]


def test_search_ranks_are_sequential(client):
    data = client.post("/api/v1/search", json=IOL_PAYLOAD).json()
    ranks = [r["rank"] for r in data["results"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_search_iol_ranks_acrylic_higher_than_silicone(client):
    data = client.post("/api/v1/search", json=IOL_PAYLOAD).json()
    results = data["results"]
    by_pmid = {r["pmid"]: r for r in results}

    # DEMO001 = hydrophobic acrylic IOL, DEMO004 = silicone IOL
    if "DEMO001" in by_pmid and "DEMO004" in by_pmid:
        assert by_pmid["DEMO001"]["rank"] < by_pmid["DEMO004"]["rank"], (
            "Hydrophobic acrylic IOL should outrank silicone IOL for an acrylic target"
        )


def test_search_antivegf_query(client):
    data = client.post("/api/v1/search", json=ANTIVEGF_PAYLOAD).json()
    results = data["results"]
    assert len(results) >= 1


def test_search_empty_query_rejected(client):
    r = client.post("/api/v1/search", json={"query": ""})
    assert r.status_code == 422


def test_search_deterministic(client):
    """Same request must return identical scores on repeated calls."""
    r1 = client.post("/api/v1/search", json=IOL_PAYLOAD).json()["results"]
    r2 = client.post("/api/v1/search", json=IOL_PAYLOAD).json()["results"]
    for a, b in zip(r1, r2):
        assert a["composite_score"] == b["composite_score"]
        assert a["rank"] == b["rank"]


def test_search_custom_weights(client):
    payload = dict(IOL_PAYLOAD)
    payload["weights"] = {"R": 0.5, "P": 0.2, "M": 0.15, "E": 0.15}
    r = client.post("/api/v1/search", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) >= 1


def test_search_weights_must_sum_to_one(client):
    payload = dict(IOL_PAYLOAD)
    payload["weights"] = {"R": 0.5, "P": 0.5, "M": 0.5, "E": 0.5}
    r = client.post("/api/v1/search", json=payload)
    assert r.status_code == 422


def test_search_pool_size_below_max_results_rejected(client):
    payload = dict(IOL_PAYLOAD)
    payload["pool_size"] = 10
    payload["max_results"] = 50
    r = client.post("/api/v1/search", json=payload)
    assert r.status_code == 422


def test_search_stream_demo_emits_sse_done(client):
    """Streaming endpoint returns SSE with status + done (demo uses fixtures, no triage events)."""
    with client.stream("POST", "/api/v1/search/stream", json=IOL_PAYLOAD) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")
    assert "event: status" in body
    assert "event: done" in body
    assert '"mode": "demo"' in body


def test_live_stream_emits_triage_sse_event_names():
    """Live `_stream_search` must emit `pool` batches and `accept` for the UI contract."""
    import inspect

    from app.api import search as search_mod

    full = inspect.getsource(search_mod._stream_search)
    assert '"pool"' in full and "_sse(" in full
    assert '"accept"' in full  # may be wrapped across lines: yield _sse(\n    "accept",
    assert "triage_complete" not in full
    assert "pool_start" not in full
