import geopandas as gpd

from ingest import common
from tests.conftest import load_script


def test_grid_from_polygon_yields_res9_cells():
    grid = load_script("00_grid")
    poly = gpd.read_file(common.FIXTURES / "raw_sample/county.geojson").geometry.iloc[0]
    df = grid.build_grid(poly)
    assert {"h3", "lat", "lng", "wkt"} <= set(df.columns)
    assert 100 < len(df) < 1000
    assert df["h3"].is_unique
