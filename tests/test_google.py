import pandas as pd
import requests

from tests.conftest import load_script


def test_parse_place_maps_fields():
    g = load_script("05_google_places")
    p = {"id": "abc", "displayName": {"text": "Seoul Bulgogi"}, "location": {"latitude": 40.44, "longitude": -79.99},
         "rating": 4.5, "userRatingCount": 120, "priceLevel": "PRICE_LEVEL_MODERATE",
         "businessStatus": "OPERATIONAL", "types": ["korean_restaurant", "restaurant"],
         "editorialSummary": {"text": "Casual Korean spot."}}
    r = g.parse_place(p)
    assert r["price_level"] == 2 and r["reviews"] == 120 and r["google_open"] is True
    assert r["cuisine_key"] == "korean"


def test_parse_place_google_open_is_false_only_for_closed_permanently():
    """Contract: is_open depends on businessStatus != CLOSED_PERMANENTLY, not on == OPERATIONAL.
    CLOSED_TEMPORARILY and BUSINESS_STATUS_UNSPECIFIED must still read as open."""
    g = load_script("05_google_places")
    base = {"id": "x", "displayName": {"text": "Place"}, "location": {"latitude": 40.44, "longitude": -79.99}}
    assert g.parse_place({**base, "businessStatus": "CLOSED_TEMPORARILY"})["google_open"] is True
    assert g.parse_place({**base, "businessStatus": "BUSINESS_STATUS_UNSPECIFIED"})["google_open"] is True
    assert g.parse_place({**base, "businessStatus": "CLOSED_PERMANENTLY"})["google_open"] is False


def test_match_does_not_leak_cuisine_from_distant_same_name_match():
    """A Google place that matches on normalized name but fails the 150m distance check must not
    donate its cuisine_key to the WPRDC row — only real matches (source=wprdc+google) may."""
    g = load_script("05_google_places")
    w = pd.DataFrame({"id": ["wprdc:1"], "name": ["Golden Dragon"], "lat": [40.40], "lng": [-79.99],
                      "is_open": [True], "provider_id": ["1"], "cuisine_key": [None], "categories": [["restaurant"]],
                      "h3": ["x"], "provider": ["wprdc"], "source": ["wprdc"], "address": ["a"]})
    gg = pd.DataFrame([g.parse_place({"id": "far", "displayName": {"text": "Golden Dragon"},
                                      "location": {"latitude": 40.625, "longitude": -79.99},
                                      "rating": 4.0, "userRatingCount": 10, "businessStatus": "OPERATIONAL",
                                      "types": ["chinese_restaurant", "restaurant"]})])
    out = g.match(w, gg)
    row = out.loc[out.id == "wprdc:1"].iloc[0]
    assert row["source"] == "wprdc"
    assert pd.isna(row["rating"])
    assert pd.isna(row["cuisine_key"])


def test_fetch_all_falls_back_to_empty_frame_on_request_failure(monkeypatch):
    """If Google fetch fails outright (e.g. quota exhausted), fetch_all must not raise — main() then
    degrades to WPRDC-only output instead of aborting the whole ingest."""
    g = load_script("05_google_places")

    def boom(c):
        raise requests.exceptions.RequestException("quota exceeded")

    monkeypatch.setattr(g, "fetch_cell", boom)
    out = g.fetch_all(["882a840137fffff"])
    assert out.empty
    assert list(out.columns) == g.GOOGLE_COLS


def test_fetch_all_keeps_places_fetched_before_a_later_cell_fails(monkeypatch):
    """A failure partway through a county run must not discard the cells that already succeeded —
    the exact bug that hit the real run once and will hit it again once quota lifts mid-run."""
    g = load_script("05_google_places")
    calls = []
    ok_place = {"id": "abc", "displayName": {"text": "Golden Dragon"},
                "location": {"latitude": 40.44, "longitude": -79.99},
                "businessStatus": "OPERATIONAL", "types": ["restaurant"]}

    def fetch(c):
        calls.append(c)
        if c == "fail_me":
            raise requests.exceptions.RequestException("quota exceeded")
        return [ok_place]

    monkeypatch.setattr(g, "fetch_cell", fetch)
    out = g.fetch_all(["cell1", "cell2", "fail_me", "cell4"])
    assert len(out) == 2  # cell1 and cell2's places survive the later failure
    assert calls == ["cell1", "cell2", "fail_me"]  # stopped at the failure, never reached cell4


def test_match_falls_back_to_wprdc_only_when_google_is_empty():
    """The WPRDC-only fallback: an empty (correctly-columned) google frame — what fetch_all returns
    when Google fetch fails outright — must not crash match() and must produce plain WPRDC rows."""
    g = load_script("05_google_places")
    w = pd.DataFrame({"id": ["wprdc:1"], "name": ["Golden Dragon"], "lat": [40.40], "lng": [-79.99],
                      "is_open": [True], "provider_id": ["1"], "cuisine_key": ["chinese"], "categories": [["restaurant"]],
                      "h3": ["x"], "provider": ["wprdc"], "source": ["wprdc"], "address": ["a"]})
    empty_google = pd.DataFrame(columns=g.GOOGLE_COLS)
    out = g.match(w, empty_google)
    row = out.loc[out.id == "wprdc:1"].iloc[0]
    assert row["source"] == "wprdc"
    assert row["is_open"] == w.is_open.item()
    assert row["cuisine_key"] == "chinese"
    assert pd.isna(row["rating"])


def test_match_by_name_and_distance():
    g = load_script("05_google_places")
    w = pd.DataFrame({"id": ["wprdc:1"], "name": ["Seoul Bulgogi House"], "lat": [40.4400], "lng": [-79.9900],
                      "is_open": [True], "provider_id": ["1"], "cuisine_key": ["korean"], "categories": [["restaurant"]],
                      "h3": ["x"], "provider": ["wprdc"], "source": ["wprdc"], "address": ["a"]})
    gg = pd.DataFrame([g.parse_place({"id": "abc", "displayName": {"text": "Seoul Bulgogi"},
                                      "location": {"latitude": 40.4405, "longitude": -79.9902},
                                      "rating": 4.5, "userRatingCount": 120, "priceLevel": "PRICE_LEVEL_MODERATE",
                                      "businessStatus": "OPERATIONAL", "types": ["restaurant"]})])
    out = g.match(w, gg)
    assert out.loc[out.id == "wprdc:1", "rating"].item() == 4.5
    assert out.loc[out.id == "wprdc:1", "source"].item() == "wprdc+google"
