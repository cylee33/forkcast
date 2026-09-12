import pandas as pd

from tests.conftest import load_script


def test_classify_tags():
    osm = load_script("04_osm_pois")
    assert osm.classify({"amenity": "university"}) == "university"
    assert osm.classify({"shop": "supermarket"}) == "supermarket"
    assert osm.classify({"shop": "supermarket", "cuisine": "asian"}) == "asian_grocer"
    assert osm.classify({"amenity": "parking"}) == "parking"
    assert osm.classify({"railway": "station"}) == "transit_station"
    assert osm.classify({"foo": "bar"}) is None


def test_cell_metrics_counts_and_distances():
    import h3
    osm = load_script("04_osm_pois")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    lat, lng = h3.cell_to_latlng(c)
    cells = pd.DataFrame({"h3": [c], "lat": [lat], "lng": [lng]})
    pois = pd.DataFrame({"osm_id": [1, 2], "name": ["Pitt", "Giant Eagle"], "kind": ["university", "supermarket"],
                         "lat": [lat, lat + 0.01], "lng": [lng, lng], "h3": [c, h3.latlng_to_cell(lat + 0.01, lng, 9)]})
    out = osm.cell_metrics(pois, cells, roads_h3={c}, gtfs_trips=pd.Series({c: 120.0})).set_index("h3")
    assert out.loc[c, "anchor_university"] == 1
    assert 0.9 < out.loc[c, "dist_to_supermarket_km"] < 1.3
    assert out.loc[c, "main_road_frontage"] == 1
    assert out.loc[c, "transit_daily_trips"] == 120.0
