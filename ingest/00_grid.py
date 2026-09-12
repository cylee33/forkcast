"""H3 res-9 grid for Allegheny County → data/processed/geo_cells.parquet + geo_cells table."""
import geopandas as gpd
import h3
import pandas as pd
import requests
from sqlalchemy import text

from ingest import common

COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"


def county_polygon():
    path = common.RAW / "tiger/cb_2023_us_county_500k.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(COUNTY_URL, timeout=120).content)
    gdf = gpd.read_file(f"zip://{path}")
    row = gdf[(gdf.STATEFP == common.STATE_FIPS) & (gdf.COUNTYFP == common.COUNTY_FIPS)]
    return row.geometry.iloc[0]


def build_grid(poly) -> pd.DataFrame:
    cells = sorted(h3.geo_to_cells(poly, common.H3_RES))
    rows = []
    for c in cells:
        lat, lng = h3.cell_to_latlng(c)
        rows.append({"h3": c, "lat": lat, "lng": lng, "wkt": common.cell_polygon(c).wkt})
    return pd.DataFrame(rows)


def main():
    args = common.cli(__doc__)
    df = build_grid(county_polygon())
    if args.limit:
        df = df.head(args.limit)
    common.save(df, "geo_cells")
    if not args.no_db:
        eng = common.engine()
        with eng.begin() as con:
            con.execute(text("DELETE FROM geo_cells"))
        common.write_table(df.rename(columns={"wkt": "geom"}), "geo_cells_stage")
        with eng.begin() as con:
            con.execute(text("""INSERT INTO geo_cells (h3, lat, lng, geom)
                                SELECT h3, lat, lng, ST_GeomFromText(geom, 4326) FROM geo_cells_stage"""))
            con.execute(text("DROP TABLE geo_cells_stage"))
    print(f"geo_cells: {len(df)} cells")


if __name__ == "__main__":
    main()
