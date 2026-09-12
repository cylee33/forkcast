import pandas as pd

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
