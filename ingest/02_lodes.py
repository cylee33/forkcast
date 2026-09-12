"""LODES WAC 2021 (PA) → daytime workers per cell."""
import importlib.util

import pandas as pd
import requests

from ingest import common

URL = "https://lehd.ces.census.gov/data/lodes/LODES8/pa/wac/pa_wac_S000_JT00_2021.csv.gz"


def fetch() -> pd.DataFrame:
    path = common.RAW / "lodes/pa_wac_S000_JT00_2021.csv.gz"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(URL, timeout=300).content)
    df = pd.read_csv(path, dtype={"w_geocode": str}, usecols=["w_geocode", "C000", "CE03"])
    return df[df.w_geocode.str.startswith(common.STATE_FIPS + common.COUNTY_FIPS)]


def to_block_groups(df: pd.DataFrame) -> pd.DataFrame:
    g = df.assign(GEOID=df.w_geocode.str[:12]).groupby("GEOID")
    return g.agg(workers_daytime=("C000", "sum"), workers_high_wage=("CE03", "sum")).reset_index()


def main():
    args = common.cli(__doc__)
    bg = to_block_groups(fetch())
    if args.limit:
        bg = bg.head(args.limit)
    spec = importlib.util.spec_from_file_location("acs", common.ROOT / "ingest/01_census_acs.py")
    acs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acs)
    gdf = acs.block_groups().merge(bg, on="GEOID")
    cells = common.area_weight(gdf, common.cells_gdf(),
                               extensive=["workers_daytime", "workers_high_wage"], intensive=[])
    common.save(cells, "lodes")
    print(f"lodes: {len(cells)} cells, workers {cells.workers_daytime.sum():,.0f}")


if __name__ == "__main__":
    main()
