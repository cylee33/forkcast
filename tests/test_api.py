"""API-level tests: FastAPI's TestClient against `api.main.app`, with every scoring/LLM
dependency swapped for a fake via `app.dependency_overrides` (see `api/deps.py`). No test here
makes a real scoring call, a real LLM call, or a real network call. Tests that touch the
database reuse the `db_engine` fixture from `tests/conftest.py` and skip (not fail) when no
live Postgres is reachable, matching the rest of the suite's convention.
"""
import uuid
import warnings

import pytest

# starlette.testclient's module-level code triggers a DeprecationWarning (anyio.abc.BlockingPortal)
# on import with this anyio/starlette combination -- third-party, not something this suite's code
# does. Import it once here with warnings suppressed so the module executes (and gets cached in
# sys.modules) without emitting it, keeping the suite at zero warnings.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

from sqlalchemy import text

from api import deps
from api.main import app
from api.models import ConceptProfile

SUBSCORE_KEYS = ["D", "C", "T", "A", "S_spend", "K", "Sup"]


def _profile_kwargs(**overrides) -> dict:
    base = dict(
        concept_name="Korean street food", cuisines=["korean"], service_format="fast_casual",
        price_tier=1, avg_ticket_usd=13.0, dayparts={"lunch": 0.3, "dinner": 0.4, "late_night": 0.3},
        customer_archetypes=["students", "young_adults"], income_fit="medium", catchment="walk",
        catchment_tau_min=8.0, footprint_sqft=(800, 1500), seats=24, supplier_types=["asian_grocer"],
        direct_competitor_description="Korean fast-casual counters", is_franchise=False,
        proposed_weights={"D": 0.25, "C": 0.18, "T": 0.22, "A": 0.15, "S_spend": 0.08, "K": 0.09, "Sup": 0.03},
        confidence=0.8,
    )
    base.update(overrides)
    return base


def _feature(h3_id: str, zone_id: int | None, sup: float | None = 40.0) -> dict:
    subscores = {"D": 70.0, "C": 60.0, "T": 55.0, "A": 50.0, "S_spend": 45.0, "K": 65.0, "Sup": sup}
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 0.01], [0.01, 0.01], [0.01, 0], [0, 0]]]},
        "properties": {"h3": h3_id, "total": 62.5, "zone_id": zone_id, "confidence": 0.6, **subscores},
    }


def _zone(zone_id: int, best_h3: str, sup: float | None = None) -> dict:
    return {
        "zone_id": zone_id, "name": f"Zone {zone_id}", "total": 62.5, "best_h3": best_h3,
        "subscores": {"D": 70.0, "C": 60.0, "T": 55.0, "A": 50.0, "S_spend": 45.0, "K": 65.0, "Sup": sup},
        "confidence": 0.6, "drivers": ["Student demand high"], "risks": ["Rent unknown"],
        "gap": {"demand": 70.0, "supply": 20.0, "gap": 50.0}, "gap_flag": True,
        "competitors_direct": [], "competitors_indirect": [
            {"id": "google:x", "name": "Sushi Fuku", "distance_m": 210.0, "similarity": 0.62,
             "rating": 4.4, "reviews": 800},
        ],
        "anchors": [{"name": "University of Pittsburgh", "type": "university", "distance_m": 300.0}],
        # est_rent_psf_yr is NULL on every cell (Phase 1 data), so a real analysis always carries
        # this through as null -- never a fabricated number.
        "est_rent_psf_yr": None, "rent_confidence": 0.0,
    }


def fake_analyze(profile: ConceptProfile, center: tuple[float, float], radius_mi: float,
                  weights: dict[str, float] | None = None) -> dict:
    analysis_id = f"test-{uuid.uuid4().hex}"
    h3_id = "892a8470603ffff"
    return {
        "analysis_id": analysis_id, "profile": profile.model_dump(mode="json"), "weights": weights,
        "cells": {"type": "FeatureCollection", "features": [_feature(h3_id, zone_id=1, sup=None)]},
        "zones": [_zone(1, h3_id, sup=None)],  # Sup absent by design: exercises the None passthrough
        "backtest_rho": None,
    }


def fake_parse(text: str) -> ConceptProfile:
    return ConceptProfile(**_profile_kwargs(concept_name=text[:40] or "Parsed concept"))


def fake_refine(profile: ConceptProfile, instruction: str) -> tuple[ConceptProfile, dict]:
    patched = profile.model_copy(update={"concept_name": profile.concept_name + " (refined)"})
    return patched, {"concept_name": {"from": profile.concept_name, "to": patched.concept_name}}


def fake_explain(profile: ConceptProfile, zone: dict) -> str:
    return f"{profile.concept_name} fits zone {zone.get('zone_id')} on demand and traffic."


def fake_reverse(lat: float, lng: float, sqft=None, rent=None, top_n: int = 8) -> list[dict]:
    return [{"concept_name": f"Archetype {i}", "total": 90.0 - i, "subscores": {"D": 80.0}, "why": "x"}
            for i in range(top_n)]


@pytest.fixture(autouse=True)
def _fake_dependencies():
    app.dependency_overrides[deps.get_analyze] = lambda: fake_analyze
    app.dependency_overrides[deps.get_concept_parser] = lambda: fake_parse
    app.dependency_overrides[deps.get_refiner] = lambda: fake_refine
    app.dependency_overrides[deps.get_explainer] = lambda: fake_explain
    app.dependency_overrides[deps.get_reverser] = lambda: fake_reverse
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_parse_happy_path(client):
    r = client.post("/api/concept/parse", json={"text": "Korean street food truck"})
    assert r.status_code == 200
    body = r.json()
    assert body["concept_name"].startswith("Korean street food")
    assert body["cuisines"] == ["korean"]


def test_parse_rejects_malformed_body(client):
    r = client.post("/api/concept/parse", json={})  # missing required "text"
    assert 400 <= r.status_code < 500
    assert "error" in r.json()


def test_refine_happy_path(client):
    r = client.post("/api/concept/refine", json={
        "profile": _profile_kwargs(), "instruction": "make it more upscale",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["concept_name"].endswith("(refined)")
    assert "concept_name" in body["diff"]


def test_refine_rejects_malformed_profile(client):
    bad_profile = _profile_kwargs()
    bad_profile["price_tier"] = 9  # out of the 1-4 range
    r = client.post("/api/concept/refine", json={"profile": bad_profile, "instruction": "x"})
    assert 400 <= r.status_code < 500


def test_analysis_happy_path_and_none_passthrough(client):
    r = client.post("/api/analysis", json={
        "profile": _profile_kwargs(), "center": {"lat": 40.44, "lng": -79.95}, "radius_mi": 0.5,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["backtest_rho"] is None
    # An absent sub-score must reach the client as null, never coerced to 0.
    assert body["zones"][0]["subscores"]["Sup"] is None
    assert body["cells"]["features"][0]["properties"]["h3"] == "892a8470603ffff"
    assert body["zones"][0]["est_rent_psf_yr"] is None


def test_analysis_rejects_bad_radius(client):
    r = client.post("/api/analysis", json={
        "profile": _profile_kwargs(), "center": {"lat": 40.44, "lng": -79.95}, "radius_mi": -1,
    })
    assert r.status_code == 422


def test_analysis_rejects_out_of_range_weight(client):
    r = client.post("/api/analysis", json={
        "profile": _profile_kwargs(), "center": {"lat": 40.44, "lng": -79.95}, "radius_mi": 0.5,
        "weights": {"D": 1.5, "C": 0.1, "T": 0.1, "A": 0.1, "S_spend": 0.1, "K": 0.05, "Sup": 0.05},
    })
    assert r.status_code == 400
    assert "error" in r.json()


def test_analysis_persists_and_replay_reconstructs_honestly(client, db_engine):
    r = client.post("/api/analysis", json={
        "profile": _profile_kwargs(), "center": {"lat": 40.44, "lng": -79.95}, "radius_mi": 0.5,
    })
    assert r.status_code == 200
    analysis_id = r.json()["analysis_id"]
    try:
        with db_engine.connect() as con:
            row = con.execute(text("SELECT weights_json, model_json FROM analyses WHERE id = :id"),
                               {"id": analysis_id}).mappings().first()
        assert row is not None
        assert set(row["weights_json"]) == set(SUBSCORE_KEYS)
        assert row["model_json"]["concept_parser"] == "gemini-3.8-flash"

        replay = client.get(f"/api/analysis/{analysis_id}")
        assert replay.status_code == 200
        replayed = replay.json()
        assert replayed["analysis_id"] == analysis_id
        assert len(replayed["cells"]["features"]) == 1
        assert replayed["cells"]["features"][0]["properties"]["Sup"] is None
        # Replay can only honestly reconstruct what analysis_cells actually stores; narrative
        # zone fields never persisted must come back empty, not fabricated.
        assert replayed["zones"][0]["drivers"] == []
        assert replayed["zones"][0]["competitors_direct"] == []
        assert replayed["zones"][0]["est_rent_psf_yr"] is None
        assert replayed["backtest_rho"] is None
    finally:
        with db_engine.begin() as con:
            con.execute(text("DELETE FROM analysis_cells WHERE analysis_id = :id"), {"id": analysis_id})
            con.execute(text("DELETE FROM analyses WHERE id = :id"), {"id": analysis_id})


def test_analysis_replay_missing_id_is_404(client):
    r = client.get("/api/analysis/does-not-exist")
    assert r.status_code == 404
    assert "error" in r.json()


def test_explain_happy_path(client):
    r = client.post("/api/explain", json={
        "profile": _profile_kwargs(), "zone": {"zone_id": 1, "subscores": {"D": 70.0}},
    })
    assert r.status_code == 200
    assert "zone 1" in r.json()["text"]


def test_reverse_happy_path(client):
    r = client.post("/api/reverse", json={"lat": 40.44, "lng": -79.95, "sqft": 1200, "rent": 30.0})
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 8


def test_reverse_rejects_bad_top_n(client):
    r = client.post("/api/reverse", json={"lat": 40.44, "lng": -79.95, "top_n": 99})
    assert r.status_code == 422


def test_meta_reports_null_backtest_and_model_names(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == {"concept_parser": "gemini-3.8-flash", "embeddings": "gemini-embedding-001"}
    # No backtest has been run yet -- this must be null, never a plausible-looking number.
    assert body["backtest_rho"] is None
    assert body["backtest_n"] is None


def test_normalize_weights_clamps_and_renormalizes():
    weights = deps.normalize_weights({"D": 0.9, "C": 0.1, "T": 0.0, "A": 0.0,
                                       "S_spend": 0.0, "K": 0.0, "Sup": 0.0})
    # 0.9 is clamped to 0.4 before renormalizing, so no single weight can still dominate at 0.9.
    assert weights["D"] == pytest.approx(0.4 / 0.5)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_normalize_weights_rejects_out_of_range():
    with pytest.raises(ValueError):
        deps.normalize_weights({"D": 1.5})
