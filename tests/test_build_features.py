import h3
import pandas as pd

from tests.conftest import load_script


def _cells(n=3):
    base = h3.latlng_to_cell(40.44, -79.99, 9)
    cs = list(h3.grid_disk(base, 1))[:n]
    return pd.DataFrame({"h3": cs, "lat": [h3.cell_to_latlng(c)[0] for c in cs], "lng": [h3.cell_to_latlng(c)[1] for c in cs]})


def test_join_and_percentiles_cover_contract_columns():
    b = load_script("12_build_features")
    cells = _cells()
    parts = {name: pd.DataFrame({"h3": cells.h3}) for name in
             ["acs", "lodes", "osm_cells", "activity_cells", "spend", "rent", "affinity"]}
    for col, part_name in b.PART_OF.items():
        parts[part_name][col] = [1.0, 2.0, 3.0]
    parts["activity_cells"]["traffic_source"] = "proxy"
    parts["rent"]["rent_source"], parts["rent"]["rent_resolution"], parts["rent"]["rent_confidence"] = "x", "zip", 0.5
    parts["affinity"]["cuisine_affinity"] = [{"korean": 50.0}] * 3
    places = pd.DataFrame({"h3": [cells.h3[0]], "is_open": [True]})
    df = b.add_percentiles(b.join_all(parts, cells, places))
    for col in b.NUMERIC:
        assert col in df.columns, col
        assert f"{col}_pct" in df.columns, col
        assert df[f"{col}_pct"].between(0, 100).all()
    assert not df[b.NUMERIC].isna().any().any()
