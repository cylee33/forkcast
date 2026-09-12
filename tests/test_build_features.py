import json

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


def test_join_leaves_column_nan_when_backing_part_is_entirely_absent():
    """rent.parquet does not exist in production, so `parts` never gets a "rent" key at all.
    est_rent_psf_yr must come back NaN (unmeasured), not 0.0 (a fabricated free-rent value)."""
    b = load_script("12_build_features")
    cells = _cells()
    parts = {name: pd.DataFrame({"h3": cells.h3}) for name in
             ["acs", "lodes", "osm_cells", "activity_cells", "spend", "affinity"]}
    for col, part_name in b.PART_OF.items():
        if part_name in parts:
            parts[part_name][col] = [1.0, 2.0, 3.0]
    parts["activity_cells"]["traffic_source"] = "proxy"
    parts["affinity"]["cuisine_affinity"] = [{"korean": 50.0}] * 3
    places = pd.DataFrame({"h3": [cells.h3[0]], "is_open": [True]})
    df = b.add_percentiles(b.join_all(parts, cells, places))
    assert df["est_rent_psf_yr"].isna().all()
    assert df["est_rent_psf_yr_pct"].isna().all()
    # a present part's values (including a real zero for no anchor nearby) must still be filled, not left NaN
    assert df["anchor_university"].notna().all()
    assert list(df["anchor_university"]) == [1.0, 2.0, 3.0]


def test_median_hh_income_jam_nan_survives_the_join_not_zeroed():
    """acs.parquet carries a genuine per-row NaN for a jam-masked block group even though the
    "acs" part itself is present. The generic fillna(0.0) in join_all's NUMERIC loop must not
    re-zero it -- that would silently reproduce the $0-income defect Fix 1 removes upstream."""
    b = load_script("12_build_features")
    cells = _cells()
    parts = {name: pd.DataFrame({"h3": cells.h3}) for name in
             ["acs", "lodes", "osm_cells", "activity_cells", "spend", "rent", "affinity"]}
    for col, part_name in b.PART_OF.items():
        parts[part_name][col] = [1.0, 2.0, 3.0]
    parts["acs"]["median_hh_income"] = [float("nan"), 40000.0, 80000.0]  # one jam-masked cell
    parts["activity_cells"]["traffic_source"] = "proxy"
    parts["rent"]["rent_source"], parts["rent"]["rent_resolution"], parts["rent"]["rent_confidence"] = "x", "zip", 0.5
    parts["affinity"]["cuisine_affinity"] = [{"korean": 50.0}] * 3
    places = pd.DataFrame({"h3": [cells.h3[0]], "is_open": [True]})
    df = b.add_percentiles(b.join_all(parts, cells, places))
    assert df["median_hh_income"].isna().sum() == 1
    assert pd.isna(df.loc[df["median_hh_income"].isna(), "median_hh_income"]).all()
    assert (df["median_hh_income"].dropna() > 0).all()  # the two real values are untouched
    assert df["median_hh_income_pct"].isna().sum() == 1  # NaN input -> NaN percentile, not a floor value


def test_traffic_source_is_nan_when_activity_cells_part_absent():
    """activity_cells missing entirely means there is no measurement, real or proxy, to label --
    defaulting traffic_source to "proxy" would assert a method for data that doesn't exist. The
    ACTIVITY columns it backs go NaN too (via the same PART_OF rule as est_rent_psf_yr), and that
    NaN must serialize to JSON null, not the bare float("nan") that broke postgres's jsonb cast."""
    b = load_script("12_build_features")
    cells = _cells()
    parts = {name: pd.DataFrame({"h3": cells.h3}) for name in
             ["acs", "lodes", "osm_cells", "spend", "rent", "affinity"]}  # no activity_cells
    for col, part_name in b.PART_OF.items():
        if part_name in parts:
            parts[part_name][col] = [1.0, 2.0, 3.0]
    parts["rent"]["rent_source"], parts["rent"]["rent_resolution"], parts["rent"]["rent_confidence"] = "x", "zip", 0.5
    parts["affinity"]["cuisine_affinity"] = [{"korean": 50.0}] * 3
    places = pd.DataFrame({"h3": [cells.h3[0]], "is_open": [True]})
    df = b.join_all(parts, cells, places)
    assert df["traffic_source"].isna().all()
    row = df.iloc[0]
    payload = json.dumps({d.removeprefix("activity_"): (None if pd.isna(row[d]) else float(row[d])) for d in b.ACTIVITY})
    assert json.loads(payload) == {d.removeprefix("activity_"): None for d in b.ACTIVITY}
