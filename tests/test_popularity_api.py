import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.popularity as popularity_api
from api.main import app
from ml.popularity import popularity_available

client = TestClient(app)


def test_health_and_popularity_status_are_available_without_artifacts():
    assert client.get("/health").json() == {"status": "ok"}
    prototype = client.get("/")
    assert prototype.status_code == 200
    assert "Where restaurants belong" in prototype.text
    assert client.get("/data/fixtures/recommend_sample.json").status_code == 200
    response = client.get("/api/popularity/status")
    assert response.status_code == 200
    assert response.json() == {
        "available": popularity_available(),
        "role": "optional historical online-popularity signal",
        "pittsburgh_validation": "unavailable",
    }


def test_popularity_endpoint_returns_503_without_private_artifacts(monkeypatch):
    monkeypatch.setattr(popularity_api, "popularity_available", lambda: False)
    response = client.post(
        "/api/popularity",
        json={"profile": _fixture()["profile"], "h3_ids": ["892a8470603ffff"]},
    )
    assert response.status_code == 503


@pytest.mark.skipif(
    not popularity_available(),
    reason="Yelp-derived runtime artifacts are deliberately not stored in the public repository",
)
def test_popularity_endpoint_scores_fixture_cells_in_request_order():
    fixture = _fixture()
    h3_ids = [feature["properties"]["h3"] for feature in fixture["cells"]["features"][:3]]
    response = client.post(
        "/api/popularity",
        json={"profile": fixture["profile"], "h3_ids": h3_ids},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "experimental_unvalidated_region"
    assert body["model"] == "hgb_demographics"
    assert [cell["h3"] for cell in body["cells"]] == h3_ids
    assert all(0 <= cell["historical_popularity_pct"] <= 100 for cell in body["cells"])


@pytest.mark.skipif(
    not popularity_available(),
    reason="Yelp-derived runtime artifacts are deliberately not stored in the public repository",
)
def test_popularity_endpoint_accepts_the_minimal_ui_profile():
    h3_id = _fixture()["cells"]["features"][0]["properties"]["h3"]
    response = client.post(
        "/api/popularity",
        json={"profile": {"cuisines": ["korean"], "price_tier": 2}, "h3_ids": [h3_id]},
    )
    assert response.status_code == 200
    assert response.json()["cells"][0]["h3"] == h3_id


def _fixture() -> dict:
    return json.loads(Path("data/fixtures/recommend_sample.json").read_text())
