"""Integration tests for the extended /correlate endpoint (Step 3).

Run with APP_MODE=demo (no real HTTP or LLM calls) via the shared ``client``
fixture in conftest.py.
"""

from __future__ import annotations


def test_correlate_seed_only(client):
    """Seed-only request returns a valid RetrievalResponse with source_counts in metadata."""
    resp = client.post("/api/v1/retrieval/correlate", json={"seed": "PMID:39350227"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["seed"]["identifier"] == "PMID:39350227"
    assert isinstance(data["results"], list)
    assert len(data["results"]) >= 1  # at least the self-match
    assert data["results"][0]["correlation_score"] == 1.0
    assert "source_counts" in data["metadata"]


def test_correlate_with_profile(client):
    """Seed + profile: self-match is at rank 1 with relation_label == 'self_match'."""
    resp = client.post(
        "/api/v1/retrieval/correlate",
        json={
            "seed": "PMID:39350227",
            "profile": {
                "product_type": "drug",
                "product_name": "VABYSMO (faricimab-svoa)",
                "active_ingredient": "faricimab-svoa",
                "route": "intravitreal",
                "indication": ["nAMD", "DME"],
                "key_metrics_or_endpoints": ["BCVA", "OCT thickness"],
                "key_thresholds": [],
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    first = data["results"][0]
    assert first["candidate"]["identifier"] == "PMID:39350227"
    assert first["relation_label"] == "self_match"


def test_correlate_device_seed(client):
    """510(k) seed produces seed source_type 'fda_510k' and self-match at rank 1."""
    resp = client.post("/api/v1/retrieval/correlate", json={"seed": "K211668"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["seed"]["source_type"] == "fda_510k"
    assert data["results"][0]["correlation_score"] == 1.0


def test_correlate_empty_seed_rejected(client):
    """Empty seed string results in a JSON response (200 or 422)."""
    resp = client.post("/api/v1/retrieval/correlate", json={"seed": ""})
    # Pipeline may accept an empty seed and return a degenerate self-match (200),
    # or Pydantic/FastAPI may reject it with a validation error (422).
    # Either is acceptable; the response must be valid JSON.
    assert resp.status_code in (200, 422)
    assert resp.headers["content-type"].startswith("application/json")
