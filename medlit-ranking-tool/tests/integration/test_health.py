"""Integration tests — GET /health."""


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_health_fields(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert "app_mode" in data
    assert "llm_model" in data
    assert "llm_backend" in data
    assert "pubmed_live" in data


def test_health_demo_mode(client):
    data = client.get("/health").json()
    assert data["app_mode"] == "demo"
    assert data["pubmed_live"] is False
