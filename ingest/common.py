import argparse
import os
import pathlib

import geopandas as gpd
import h3
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import Polygon
from sqlalchemy import create_engine

load_dotenv()

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
PROC = ROOT / "data/processed"
FIXTURES = ROOT / "data/fixtures"
H3_RES = 9
BBOX = (40.18, -80.37, 40.68, -79.68)  # south, west, north, east
STATE_FIPS, COUNTY_FIPS = "42", "003"
EQUAL_AREA = "EPSG:6933"  # World equal-area (meters); valid for tests anywhere and for Allegheny County


def engine():
    return create_engine(os.environ.get("DATABASE_URL",
                                        "postgresql+psycopg://forkcast:forkcast@localhost:5432/forkcast"))


def write_table(df: pd.DataFrame, name: str, if_exists: str = "replace") -> None:
    df.to_sql(name, engine(), if_exists=if_exists, index=False, method="multi", chunksize=2000)


def save(df: pd.DataFrame, name: str) -> pathlib.Path:
    PROC.mkdir(parents=True, exist_ok=True)
    path = PROC / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(PROC / f"{name}.parquet")


def load_cells() -> pd.DataFrame:
    return load("geo_cells")[["h3", "lat", "lng"]]


def cell_polygon(h: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h)])


def cells_gdf() -> gpd.GeoDataFrame:
    cells = load_cells()
    return gpd.GeoDataFrame(cells[["h3"]], geometry=[cell_polygon(h) for h in cells["h3"]], crs="EPSG:4326")


def area_weight(src: gpd.GeoDataFrame, cells: gpd.GeoDataFrame,
                extensive: list[str], intensive: list[str]) -> pd.DataFrame:
    """Extensive columns (counts) are split by area share of the source polygon.
    Intensive columns (rates, medians) are averaged weighted by intersection area."""
    s = src.to_crs(EQUAL_AREA).copy()
    s["_src_area"] = s.geometry.area
    s["_sid"] = range(len(s))
    c = cells.to_crs(EQUAL_AREA)[["h3", "geometry"]]
    inter = gpd.overlay(s, c, how="intersection", keep_geom_type=False)
    inter["_ia"] = inter.geometry.area
    out = pd.DataFrame({"h3": inter["h3"]})
    for col in extensive:
        out[col] = inter[col] * inter["_ia"] / inter["_src_area"]
    for col in intensive:
        out[col] = inter[col] * inter["_ia"]
        # Per-column intersection area, counting only rows where this column has a value: a NaN
        # source value (e.g. a Census jam sentinel) must drop its own intersection area from the
        # denominator too, or Series.sum()'s skipna dilutes the weighted average toward zero
        # instead of leaving the cell NaN when its only source for this column is unmeasured.
        out[f"_ia_{col}"] = inter["_ia"].where(inter[col].notna())
    out["_ia"] = inter["_ia"]
    g = out.groupby("h3")
    res = g[extensive].sum() if extensive else pd.DataFrame(index=g.size().index)
    for col in intensive:
        # A group summing to 0 area means every source row for this column was NaN (e.g. all jam
        # values); mask the denominator to NaN there so the division yields NaN, not a 0/0 warning.
        den = g[f"_ia_{col}"].sum().replace(0.0, float("nan"))
        res[col] = g[col].sum() / den
    return res.reset_index()


def points_to_h3(df: pd.DataFrame, lat: str = "lat", lng: str = "lng") -> pd.DataFrame:
    df = df.copy()
    df["h3"] = [h3.latlng_to_cell(a, b, H3_RES) for a, b in zip(df[lat], df[lng])]
    return df


def disk_sum(s: pd.Series, k: int) -> pd.Series:
    """s indexed by h3. Returns, for every index cell, the sum over grid_disk(k)."""
    d = s.to_dict()
    return pd.Series({h: sum(d.get(n, 0.0) for n in h3.grid_disk(h, k)) for h in s.index})


def pct(s: pd.Series) -> pd.Series:
    """Percentile rank in [0, 100]. Uses method="min" (competition ranking) rather than
    "average" so a block of cells tied at the floor -- e.g. 97% of cells with zero signal
    for a rare cuisine or anchor type -- lands near 0 (rank 1 of N), not at the block's
    midpoint (~50). Ties still receive equal values; the max still lands at/near 100."""
    return s.rank(pct=True, method="min") * 100.0


def cli(description: str) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--limit", type=int, default=None, help="process only N rows (smoke run)")
    p.add_argument("--no-db", action="store_true", help="write parquet only")
    return p.parse_args()
