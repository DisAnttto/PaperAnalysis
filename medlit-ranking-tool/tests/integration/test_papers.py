"""Integration tests — GET /api/v1/papers/{pmid}."""

KNOWN_PMID = "DEMO001"
UNKNOWN_PMID = "NOTEXIST"


def test_get_paper_returns_200(client):
    r = client.get(f"/api/v1/papers/{KNOWN_PMID}")
    assert r.status_code == 200


def test_get_paper_shape(client):
    data = client.get(f"/api/v1/papers/{KNOWN_PMID}").json()
    assert data["pmid"] == KNOWN_PMID
    assert "title" in data
    assert "abstract" in data


def test_get_paper_404_for_unknown(client):
    r = client.get(f"/api/v1/papers/{UNKNOWN_PMID}")
    assert r.status_code == 404


def test_extract_paper_returns_200(client):
    r = client.post(f"/api/v1/papers/{KNOWN_PMID}/extract")
    assert r.status_code == 200


def test_extract_paper_shape(client):
    data = client.post(f"/api/v1/papers/{KNOWN_PMID}/extract").json()
    assert "paper_synopsis" in data
    assert "topical_relevance" in data


def test_extract_paper_404_for_unknown(client):
    r = client.post(f"/api/v1/papers/{UNKNOWN_PMID}/extract")
    assert r.status_code == 404


def test_paper_detail_returns_200(client):
    r = client.get(f"/api/v1/papers/{KNOWN_PMID}/detail")
    assert r.status_code == 200


def test_paper_detail_shape(client):
    data = client.get(f"/api/v1/papers/{KNOWN_PMID}/detail").json()
    assert "paper" in data
    assert "extraction" in data
    assert "normalized" in data
    assert data["mode"] == "demo"


def test_paper_detail_normalized_product(client):
    data = client.get(f"/api/v1/papers/{KNOWN_PMID}/detail").json()
    norm = data["normalized"]
    assert norm is not None
    assert norm["product_type"] in ("device", "drug", "both", "unknown")


def test_all_demo_papers_accessible(client):
    """Every seeded paper must be retrievable via the API."""
    for pmid in ["DEMO001", "39350227", "DEMO003", "DEMO004", "DEMO005", "DEMO006"]:
        r = client.get(f"/api/v1/papers/{pmid}")
        assert r.status_code == 200, f"Expected 200 for {pmid}, got {r.status_code}"
