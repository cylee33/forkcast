"""Tests for the pure helpers behind the Streamlit app: response parsing/shaping, color
scaling, and the null-versus-zero formatting that is the app's central rendering rule.
Streamlit's rendering loop itself is not tested here - only the importable functions it
calls. Run with `pytest app/test_app.py` (the repo's `pyproject.toml` `testpaths` is
`["tests"]`, so `make test` does not pick this file up; it must be run explicitly)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app import api_client, formatting


# ---------------------------------------------------------------------------
# Null-versus-zero formatting - the central rule
# ---------------------------------------------------------------------------


def test_format_score_none_is_not_zero():
    assert formatting.format_score(None) == "no data"
    assert formatting.format_score(0) == "0"
    assert formatting.format_score(0.0) != formatting.format_score(None)


def test_score_bar_fraction_none_stays_none():
    assert formatting.score_bar_fraction(None) is None
    assert formatting.score_bar_fraction(0) == 0.0
    assert formatting.score_bar_fraction(50) == 0.5
    assert formatting.score_bar_fraction(150) == 1.0  # clamped


def test_color_for_score_none_is_visually_distinct_from_zero():
    null_color = formatting.color_for_score(None)
    zero_color = formatting.color_for_score(0)
    assert null_color != zero_color
    assert null_color == formatting.NULL_COLOR


def test_color_for_score_interpolates_within_bounds():
    low = formatting.color_for_score(0)
    mid = formatting.color_for_score(50)
    high = formatting.color_for_score(100)
    assert low != mid != high
    for color in (low, mid, high):
        assert len(color) == 4
        assert all(0 <= c <= 255 for c in color)


def test_format_rent_unknown_when_null_or_zero_confidence():
    assert formatting.format_rent(None, 0.0) == "Rent: unknown (no data yet)"
    assert formatting.format_rent(None, None) == "Rent: unknown (no data yet)"
    assert formatting.format_rent(25.0, 0.0) == "Rent: unknown (no data yet)"


def test_format_rent_known():
    result = formatting.format_rent(25.0, 0.8)
    assert "$25" in result
    assert "80%" in result


def test_format_backtest_rho_not_yet_run():
    assert formatting.format_backtest_rho(None) == "Backtest not yet run"


def test_format_backtest_rho_known():
    assert formatting.format_backtest_rho(0.42) == "ρ = 0.42"
    assert formatting.format_backtest_rho(0.42, n=100) == "ρ = 0.42 (n=100)"


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------


def test_rank_zones_sorts_descending():
    zones = [{"total": 50}, {"total": 90}, {"total": 70}]
    ranked = formatting.rank_zones(zones)
    assert [z["total"] for z in ranked] == [90, 70, 50]
    assert zones[0]["total"] == 50  # input untouched


def test_build_hex_records_never_colors_null_as_measured():
    cells = {
        "features": [
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "h3": "892a8470603ffff",
                    "total": 60.0,
                    "D": 60.0,
                    "C": 60.0,
                    "T": 60.0,
                    "A": 60.0,
                    "S_spend": 60.0,
                    "K": None,
                    "Sup": 60.0,
                    "confidence": 0.6,
                    "zone_id": 1,
                },
            }
        ]
    }
    records = formatting.build_hex_records(cells, metric_key="K")
    assert len(records) == 1
    record = records[0]
    assert record["K_display"] == "no data"
    assert tuple(record["fill_color"]) == formatting.NULL_COLOR
    # A non-null metric still colors normally.
    records_total = formatting.build_hex_records(cells, metric_key="total")
    assert tuple(records_total[0]["fill_color"]) != formatting.NULL_COLOR


def test_diff_profile_reports_only_changed_fields():
    before = {"price_tier": 1, "cuisines": ["korean"], "avg_ticket_usd": 13}
    after = {"price_tier": 3, "cuisines": ["korean"], "avg_ticket_usd": 45}
    diff = formatting.diff_profile(before, after)
    assert len(diff) == 2
    assert any("price_tier" in line for line in diff)
    assert any("avg_ticket_usd" in line for line in diff)
    assert not any("cuisines" in line for line in diff)


def test_apply_profile_edits_does_not_mutate_original():
    profile = {"price_tier": 1, "cuisines": ["korean"]}
    edited = formatting.apply_profile_edits(profile, {"price_tier": 3})
    assert edited["price_tier"] == 3
    assert profile["price_tier"] == 1
    assert edited["cuisines"] == ["korean"]


def test_apply_refine_response_with_explicit_diff():
    before = {"price_tier": 1}
    response = {"profile": {"price_tier": 4}, "diff": ["price_tier: 1 -> 4"]}
    new_profile, diff = formatting.apply_refine_response(before, response)
    assert new_profile == {"price_tier": 4}
    assert diff == ["price_tier: 1 -> 4"]


def test_apply_refine_response_computes_diff_when_absent():
    before = {"price_tier": 1, "cuisines": ["korean"]}
    response = {"profile": {"price_tier": 4, "cuisines": ["korean"]}}
    new_profile, diff = formatting.apply_refine_response(before, response)
    assert new_profile == {"price_tier": 4, "cuisines": ["korean"]}
    assert len(diff) == 1
    assert "price_tier" in diff[0]


def test_apply_refine_response_accepts_bare_profile():
    before = {"price_tier": 1}
    response = {"price_tier": 2}
    new_profile, diff = formatting.apply_refine_response(before, response)
    assert new_profile == {"price_tier": 2}
    assert diff == ["price_tier: 1 → 2"]


# ---------------------------------------------------------------------------
# Fixture fallback
# ---------------------------------------------------------------------------


def test_fixture_loads_and_is_schema_shaped():
    data = api_client.load_fixture()
    for key in ("analysis_id", "profile", "weights", "cells", "zones", "backtest_rho"):
        assert key in data
    assert data["cells"]["type"] == "FeatureCollection"
    assert len(data["cells"]["features"]) > 0
    assert len(data["zones"]) > 0
    for key in formatting.SUBSCORE_KEYS:
        assert key in data["weights"]


def test_fixture_rent_is_honestly_unknown():
    """Ground-truth check against the real fixture: every zone's rent is null/zero
    confidence right now, matching the product's no-fabricated-data rule."""
    data = api_client.load_fixture()
    for zone in data["zones"]:
        assert zone["est_rent_psf_yr"] is None
        assert not zone["rent_confidence"]


def test_get_base_url_default_and_env(monkeypatch):
    monkeypatch.delenv("FORKCAST_API", raising=False)
    assert api_client.get_base_url() == "http://localhost:8000"
    monkeypatch.setenv("FORKCAST_API", "http://example.test:9000/")
    assert api_client.get_base_url() == "http://example.test:9000"


def test_post_wraps_connection_errors():
    import requests as requests_module

    with patch.object(
        api_client.requests, "post", side_effect=requests_module.ConnectionError("refused")
    ):
        with pytest.raises(api_client.ApiUnavailable):
            api_client._post("/api/analysis", {})


def test_get_analysis_falls_back_to_fixture_on_api_failure():
    with patch.object(api_client, "run_analysis", side_effect=api_client.ApiUnavailable("down")):
        data, source, message = api_client.get_analysis({"concept_name": "x"}, {"lat": 0, "lng": 0}, 3.0)
    assert source == "fixture"
    assert message is not None
    assert "unreachable" in message
    assert data["profile"] == {"concept_name": "x"}
    assert data["cells"]["type"] == "FeatureCollection"


def test_get_analysis_uses_live_api_when_available():
    fake_response = {"analysis_id": "abc", "zones": []}
    with patch.object(api_client, "run_analysis", return_value=fake_response):
        data, source, message = api_client.get_analysis({"concept_name": "x"}, {"lat": 0, "lng": 0}, 3.0)
    assert source == "api"
    assert message is None
    assert data == fake_response


def test_analyze_concept_falls_back_when_parse_unavailable():
    with patch.object(api_client, "parse_concept", side_effect=api_client.ApiUnavailable("down")):
        data, source, message = api_client.analyze_concept("some concept", {"lat": 0, "lng": 0}, 3.0)
    assert source == "fixture"
    assert "unreachable" in message
    assert data["cells"]["type"] == "FeatureCollection"


def test_analyze_concept_runs_analysis_after_parse():
    fake_profile = {"concept_name": "parsed"}
    fake_response = {"analysis_id": "abc"}
    with patch.object(api_client, "parse_concept", return_value=fake_profile):
        with patch.object(api_client, "run_analysis", return_value=fake_response):
            data, source, message = api_client.analyze_concept(
                "some concept", {"lat": 0, "lng": 0}, 3.0
            )
    assert source == "api"
    assert message is None
    assert data == fake_response


def test_explain_or_fallback_uses_zone_drivers_when_api_down():
    zone = {"drivers": ["Student demand 91st pct"], "risks": ["Rent estimate low confidence"]}
    with patch.object(api_client, "explain_zone", side_effect=api_client.ApiUnavailable("down")):
        resp, source = api_client.explain_or_fallback({}, zone)
    assert source == "fallback"
    assert "Student demand 91st pct" in resp["text"]
    assert "Rent estimate low confidence" in resp["text"]


def test_explain_or_fallback_uses_api_when_available():
    with patch.object(api_client, "explain_zone", return_value={"text": "narrated"}):
        resp, source = api_client.explain_or_fallback({}, {"drivers": [], "risks": []})
    assert source == "api"
    assert resp == {"text": "narrated"}


def test_check_api_up_true_and_false():
    with patch.object(api_client, "_get", return_value={}):
        assert api_client.check_api_up() is True
    with patch.object(api_client, "_get", side_effect=api_client.ApiUnavailable("down")):
        assert api_client.check_api_up() is False


def test_fixture_path_resolves_to_committed_file():
    assert api_client.FIXTURE_PATH.exists()
    with open(api_client.FIXTURE_PATH) as f:
        # Confirms load_fixture() and the raw file agree - guards against a path typo.
        assert json.load(f) == api_client.load_fixture()
