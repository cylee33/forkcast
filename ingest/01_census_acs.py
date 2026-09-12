"""ACS 5-yr 2023 block groups → cell demographics. No ancestry / foreign-born tables."""
import json
import os

import geopandas as gpd
import pandas as pd
import requests

from ingest import common

YEAR = 2023
BG_SHP_URL = f"https://www2.census.gov/geo/tiger/TIGER{YEAR}/BG/tl_{YEAR}_42_bg.zip"

JAM_VALUE_MAX = -222222222  # Census ACS jam values (e.g. -666666666: "estimate not available") are
# large negative sentinels, distinct from any real count/dollar/person value; anything at or below
# the smallest defined jam value (-222222222) is a sentinel, not data.

AGE_M = {"18_24": ["007", "008", "009", "010"], "25_34": ["011", "012"],
         "35_54": ["013", "014", "015", "016"], "55p": [f"{i:03d}" for i in range(17, 26)]}
AGE_F = {k: [f"{int(v) + 24:03d}" for v in vs] for k, vs in AGE_M.items()}
INCOME = {"income_lt25k": ["002", "003", "004", "005"], "income_25_50k": ["006", "007", "008", "009", "010"],
          "income_50_75k": ["011", "012"], "income_75_100k": ["013"],
          "income_100_150k": ["014", "015"], "income_150k_plus": ["016", "017"]}

VARS = ["B01003_001E", "B11001_001E", "B19013_001E", "B19001_001E", "B01001_001E",
        "B11005_001E", "B11005_002E", "B25010_001E", "B25044_001E", "B25044_003E", "B25044_010E",
        "B25003_001E", "B25003_003E", "B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E",
        "B14007_001E", "B14007_017E", "B14007_018E"]
VARS += [f"B19001_{s}E" for ss in INCOME.values() for s in ss]
VARS += [f"B01001_{s}E" for ss in list(AGE_M.values()) + list(AGE_F.values()) for s in ss]

GEO_COLS = ["state", "county", "tract", "block group"]
MAX_VARS_PER_REQUEST = 50  # Census API caps `get=` at 50 variables


def _chunks(vars_list: list[str], size: int = MAX_VARS_PER_REQUEST) -> list[list[str]]:
    return [vars_list[i:i + size] for i in range(0, len(vars_list), size)]


def _merge_chunks(chunks: list[list[list[str]]]) -> list[list[str]]:
    """Merge Census API list-of-lists responses (header row + data rows) on geography
    columns, without duplicating or suffixing those columns."""
    merged = None
    for rows in chunks:
        d = pd.DataFrame(rows[1:], columns=rows[0])
        if merged is None:
            merged = d
        else:
            value_cols = [c for c in d.columns if c not in GEO_COLS]
            before = len(merged)
            merged = merged.merge(d[GEO_COLS + value_cols], on=GEO_COLS, how="inner")
            assert len(merged) == before, (
                f"_merge_chunks: inner join dropped rows ({before} -> {len(merged)}); "
                "a short chunk would otherwise silently drop block groups into the cache")
    return [list(merged.columns)] + merged.values.tolist()


def fetch() -> pd.DataFrame:
    path = common.RAW / "acs/bg_2023.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        key = os.environ.get("CENSUS_API_KEY")
        chunks = []
        for vars_chunk in _chunks(VARS):
            url = (f"https://api.census.gov/data/{YEAR}/acs/acs5?get={','.join(vars_chunk)}"
                   f"&for=block%20group:*&in=state:{common.STATE_FIPS}%20county:{common.COUNTY_FIPS}")
            if key:
                url += f"&key={key}"
            chunks.append(requests.get(url, timeout=120).json())
        path.write_text(json.dumps(_merge_chunks(chunks)))
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    for v in VARS:
        n = pd.to_numeric(df[v], errors="coerce")
        df[v] = n.mask(n <= JAM_VALUE_MAX).clip(lower=0)
    return df


def _share(df, num_cols, den_col):
    den = df[den_col].replace(0, pd.NA)
    share = df[num_cols].sum(axis=1) / den
    return pd.to_numeric(share, errors="coerce").fillna(0.0)


def derive(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"GEOID": df["GEOID"]})
    out["pop_total"] = df["B01003_001E"]
    out["hh_count"] = df["B11001_001E"]
    out["median_hh_income"] = df["B19013_001E"]
    for k, ss in INCOME.items():
        out[k] = _share(df, [f"B19001_{s}E" for s in ss], "B19001_001E")
    for k in AGE_M:
        cols = [f"B01001_{s}E" for s in AGE_M[k] + AGE_F[k]]
        out[f"pct_age_{k}"] = _share(df, cols, "B01001_001E")
    out["pct_families_with_kids"] = _share(df, ["B11005_002E"], "B11005_001E")
    out["avg_hh_size"] = df["B25010_001E"]
    out["pct_no_vehicle"] = _share(df, ["B25044_003E", "B25044_010E"], "B25044_001E")
    out["pct_renters"] = _share(df, ["B25003_003E"], "B25003_001E")
    out["pct_bachelors_plus"] = _share(df, ["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"], "B15003_001E")
    out["pct_students"] = _share(df, ["B14007_017E", "B14007_018E"], "B14007_001E")
    return out


def block_groups() -> gpd.GeoDataFrame:
    path = common.RAW / "tiger/tl_2023_42_bg.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(BG_SHP_URL, timeout=300).content)
    gdf = gpd.read_file(f"zip://{path}")
    return gdf[gdf.COUNTYFP == common.COUNTY_FIPS][["GEOID", "geometry"]]


EXTENSIVE = ["pop_total", "hh_count"]


def main():
    args = common.cli(__doc__)
    bg = derive(fetch())
    if args.limit:
        bg = bg.head(args.limit)
    gdf = block_groups().merge(bg, on="GEOID")
    intensive = [c for c in bg.columns if c not in EXTENSIVE + ["GEOID"]]
    cells = common.area_weight(gdf, common.cells_gdf(), extensive=EXTENSIVE, intensive=intensive)
    common.save(cells, "acs")
    print(f"acs: {len(cells)} cells, pop sum {cells.pop_total.sum():,.0f}")


if __name__ == "__main__":
    main()
