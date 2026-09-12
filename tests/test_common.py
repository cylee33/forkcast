import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from ingest import common


def test_pct_ranks_0_to_100():
    s = pd.Series([10, 20, 30, 40])
    p = common.pct(s)
    assert p.min() >= 0 and p.max() <= 100
    assert p.iloc[-1] > p.iloc[0]


def test_pct_tied_floor_block_lands_near_zero_not_midscale():
    # Realistic shape: most cells tied at zero (no signal), a handful with distinct real values.
    n_zero = 970
    s = pd.Series([0.0] * n_zero + list(range(1, 31)))
    p = common.pct(s)
    # under method="average" this tied floor block would land near 48.5 (the defect);
    # it must instead land near the bottom of the scale.
    assert p[s == 0.0].iloc[0] < 1.0
    # ties still receive equal values
    assert p[s == 0.0].nunique() == 1
    # the (unique) max still maps to exactly 100
    assert p.max() == 100.0


def test_points_to_h3_adds_res9_cell():
    df = pd.DataFrame({"lat": [40.4406], "lng": [-79.9959]})
    out = common.points_to_h3(df)
    assert out["h3"].str.len().eq(15).all()


def test_disk_sum_includes_neighbors():
    import h3
    c = h3.latlng_to_cell(40.4406, -79.9959, 9)
    n = h3.grid_disk(c, 1)[1]
    s = pd.Series({c: 1.0, n: 2.0})
    out = common.disk_sum(s, 1)
    assert out[c] == 3.0


def test_area_weight_splits_extensive_and_averages_intensive():
    src = gpd.GeoDataFrame({"pop": [100.0], "inc": [50.0]}, geometry=[box(0, 0, 2, 1)], crs="EPSG:4326")
    cells = gpd.GeoDataFrame({"h3": ["a", "b"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:4326")
    out = common.area_weight(src, cells, extensive=["pop"], intensive=["inc"]).set_index("h3")
    assert abs(out.loc["a", "pop"] - 50) < 1e-6
    assert abs(out.loc["b", "inc"] - 50) < 1e-6
