import pandas as pd

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
    import h3

    b = load_script("07_besttime")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    cells = pd.DataFrame({"h3": [c]})
    places = pd.DataFrame({"id": ["p1"], "h3": [c]})
    pa = pd.DataFrame({"place_id": ["p1"] * len(DAYPARTS), "daypart": DAYPARTS, "busyness": [90.0] * len(DAYPARTS)})
    out = b.cells_from_activity(pa, places, cells, _proxy_df(cells.h3)).set_index("h3")
    assert out.loc[c, "traffic_source"] == "real"
    assert out.loc[c, "activity_lunch"] == 90.0
