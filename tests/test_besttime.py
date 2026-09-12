import h3
import pandas as pd
import pytest

from tests.conftest import load_script

DAYPARTS = ["morning", "lunch", "afternoon", "dinner", "late_night", "weekend"]
ACTIVITY_COLS = [f"activity_{d}" for d in DAYPARTS]


def test_dayparts_from_hours_buckets_and_scales():
    b = load_script("07_besttime")
    day = [0] * 24
    day[12] = 100  # busy at noon every day
    week = [day] * 7
    out = b.dayparts_from_hours(week)
    assert set(out) == set(DAYPARTS)
    assert out["lunch"] == 100 and out["late_night"] == 0


def _proxy_df(cells_h3):
    return pd.DataFrame({"h3": cells_h3, **{c: 10.0 for c in ACTIVITY_COLS}})


def test_cells_from_activity_falls_back_to_proxy_when_no_real_data():
    b = load_script("07_besttime")
    cells = pd.DataFrame({"h3": ["a", "b"]})
    places = pd.DataFrame(columns=["id", "h3"])
    pa = pd.DataFrame(columns=["place_id", "daypart", "busyness"])
    out = b.cells_from_activity(pa, places, cells, _proxy_df(cells.h3)).set_index("h3")
    assert (out["traffic_source"] == "proxy").all()
    assert (out.loc["a", ACTIVITY_COLS] == 10.0).all()


def test_cells_from_activity_marks_real_where_a_venue_reports():
    b = load_script("07_besttime")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    cells = pd.DataFrame({"h3": [c]})
    places = pd.DataFrame({"id": ["p1"], "h3": [c]})
    pa = pd.DataFrame({"place_id": ["p1"] * len(DAYPARTS), "daypart": DAYPARTS, "busyness": [90.0] * len(DAYPARTS)})
    out = b.cells_from_activity(pa, places, cells, _proxy_df(cells.h3)).set_index("h3")
    assert out.loc[c, "traffic_source"] == "real"
    assert out.loc[c, "activity_lunch"] == 90.0


def test_cells_from_activity_blends_rings_by_distance_weight_and_averages_venues_per_cell():
    """Target cell c has no venue of its own. A ring-1 neighbor holds two venues (60, 100 ->
    averaged to 80 within that cell first); a ring-2 neighbor holds one venue (20). Blended with
    weight 1/(1+ring): (0.5*80 + (1/3)*20) / (0.5 + 1/3) == 56.0 exactly."""
    b = load_script("07_besttime")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    n1 = next(iter(h3.grid_ring(c, 1)))
    n2 = next(iter(h3.grid_ring(c, 2)))
    cells = pd.DataFrame({"h3": [c]})
    places = pd.DataFrame({"id": ["a1", "a2", "b1"], "h3": [n1, n1, n2]})
    rows = [{"place_id": pid, "daypart": d, "busyness": val}
            for pid, val in [("a1", 60.0), ("a2", 100.0), ("b1", 20.0)] for d in DAYPARTS]
    pa = pd.DataFrame(rows)
    out = b.cells_from_activity(pa, places, cells, _proxy_df(cells.h3)).set_index("h3")
    assert out.loc[c, "traffic_source"] == "real"
    assert out.loc[c, "activity_morning"] == pytest.approx(56.0)


def test_place_activity_frame_has_stable_dtypes_when_empty():
    """The empty (no-key) run must produce the same column dtypes as a real run -- otherwise the
    parquet's schema shape depends on whether BESTTIME_API_KEY_PRIVATE happened to be set."""
    b = load_script("07_besttime")
    empty = b.place_activity_frame([])
    filled = b.place_activity_frame([{"place_id": "p1", "daypart": "lunch", "busyness": 1.0}])
    assert empty.dtypes.to_dict() == filled.dtypes.to_dict()
    assert empty["busyness"].dtype == "float64"
