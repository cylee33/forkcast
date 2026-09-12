"""Join every per-cell parquet into cell_features with metro-wide percentiles, provenance maps, and DB upsert."""
import json

import pandas as pd
from sqlalchemy import text

from ingest import common

ACS = ["pop_total", "hh_count", "median_hh_income", "income_lt25k", "income_25_50k", "income_50_75k",
       "income_75_100k", "income_100_150k", "income_150k_plus", "pct_age_18_24", "pct_age_25_34", "pct_age_35_54",
       "pct_age_55p", "pct_families_with_kids", "avg_hh_size", "pct_no_vehicle", "pct_renters",
       "pct_bachelors_plus", "pct_students"]
LODES = ["workers_daytime", "workers_high_wage"]
ANCHOR_TYPES = ["university", "school", "office", "hospital", "hotel", "bar", "nightclub", "mall", "cinema",
                "stadium", "park", "attraction", "transit_station"]
OSM = [f"anchor_{k}" for k in ANCHOR_TYPES] + \
      [f"dist_to_{k}_km" for k in ["university", "hospital", "transit_station", "stadium"]] + \
      ["transit_daily_trips", "main_road_frontage", "parking_lots", "walkable_poi_density", "poi_density"] + \
      [f"dist_to_{k}_km" for k in ["wholesale", "supermarket", "seafood", "butcher", "greengrocer", "asian_grocer", "italian_grocer"]]
ACTIVITY = [f"activity_{d}" for d in ["morning", "lunch", "afternoon", "dinner", "late_night", "weekend"]]
SPEND = ["spending_capacity", "local_price_1", "local_price_2", "local_price_3", "local_price_4"]
RENT = ["est_rent_psf_yr"]
DERIVED = ["restaurants_open"]

NUMERIC = ACS + LODES + OSM + ACTIVITY + SPEND + RENT + DERIVED
PART_OF = {**{c: "acs" for c in ACS}, **{c: "lodes" for c in LODES}, **{c: "osm_cells" for c in OSM},
           **{c: "activity_cells" for c in ACTIVITY}, **{c: "spend" for c in SPEND}, **{c: "rent" for c in RENT}}
SOURCE = {**{c: "acs_5yr_2023" for c in ACS}, **{c: "lodes_wac_2021" for c in LODES},
          **{c: "osm_overpass" for c in OSM if not c.startswith("transit_daily")}, "transit_daily_trips": "gtfs_prt",
          **{c: "besttime_or_proxy" for c in ACTIVITY}, **{c: "cex_x_acs" for c in SPEND[:1]},
          **{c: "google_price_level" for c in SPEND[1:]}, "est_rent_psf_yr": "zori_manual_regression",
          "restaurants_open": "wprdc_google"}
RESOLUTION = {**{c: "block_group" for c in ACS + LODES}, **{c: "point" for c in OSM + ACTIVITY + SPEND[1:] + DERIVED},
              "spending_capacity": "block_group", "est_rent_psf_yr": "zip"}
DIST_FILL = 25.0

# Parts loaded by main(); "rent" is included here but main() only loads parts whose parquet actually
# exists on disk (Task 13's rent.parquet is deliberately absent -- see module docstring / task brief).
PART_NAMES = ["acs", "lodes", "osm_cells", "activity_cells", "spend", "rent", "affinity"]


def join_all(parts: dict[str, pd.DataFrame], cells: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    df = cells[["h3"]].copy()
    for name, part in parts.items():
        df = df.merge(part, on="h3", how="left")
    open_counts = places[places.is_open].groupby("h3").size()
    df["restaurants_open"] = common.disk_sum(open_counts.reindex(df.h3, fill_value=0.0), 1).values
    for c in NUMERIC:
        backing_part = PART_OF.get(c)
        if backing_part is not None and backing_part not in parts:
            # The whole part backing this column was never joined (e.g. rent.parquet absent) --
            # that's unmeasured, not a real zero, so leave it NaN rather than fabricate a value.
            df[c] = float("nan")
            continue
        if c not in df:
            df[c] = 0.0
        df[c] = df[c].fillna(DIST_FILL if c.startswith("dist_to_") else 0.0).astype(float)
    df["traffic_source"] = df.get("traffic_source", pd.Series("proxy", index=df.index)).fillna("proxy")
    df["rent_source"] = df.get("rent_source", pd.Series(None, index=df.index))
    df["rent_resolution"] = df.get("rent_resolution", pd.Series(None, index=df.index))
    df["rent_confidence"] = df.get("rent_confidence", pd.Series(0.0, index=df.index)).fillna(0.0)
    df["cuisine_affinity"] = df.get("cuisine_affinity", pd.Series([{}] * len(df), index=df.index))
    df["cuisine_affinity"] = df.cuisine_affinity.apply(lambda v: v if isinstance(v, dict) else {})
    return df


def add_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    pct = {f"{c}_pct": (100.0 - common.pct(df[c])) if c.startswith("dist_to_") else common.pct(df[c]) for c in NUMERIC}
    return pd.concat([df, pd.DataFrame(pct, index=df.index)], axis=1)


def main():
    args = common.cli(__doc__)
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    present = [n for n in PART_NAMES if (common.PROC / f"{n}.parquet").exists()]
    missing = [n for n in PART_NAMES if n not in present]
    if missing:
        print(f"cell_features: parts absent (not yet collected), joining without them: {missing}")
    parts = {n: common.load(n) for n in present}
    df = add_percentiles(join_all(parts, cells, common.load("places")))
    common.save(df, "cell_features")
    if not args.no_db:
        num_cols = NUMERIC + [f"{c}_pct" for c in NUMERIC]
        # NaN (a genuinely unmeasured column, e.g. est_rent_psf_yr with no rent part joined) is not
        # valid JSON -- json.dumps would emit the literal token NaN, which postgres's jsonb parser
        # rejects. Serialize it as JSON null instead, so the absence is honest there too.
        rows = [{"h3": r.h3, "features": json.dumps({c: (None if pd.isna(r[c]) else float(r[c])) for c in num_cols}),
                 "cuisine_affinity": json.dumps(r.cuisine_affinity),
                 "activity_by_daypart": json.dumps({d.removeprefix("activity_"): float(r[d]) for d in ACTIVITY}),
                 "traffic_source": r.traffic_source, "rent_source": r.rent_source, "rent_resolution": r.rent_resolution,
                 "rent_confidence": float(r.rent_confidence), "source": json.dumps(SOURCE), "resolution": json.dumps(RESOLUTION)}
                for _, r in df.iterrows()]
        common.write_table(pd.DataFrame(rows), "cell_features_stage")
        with common.engine().begin() as con:
            con.execute(text("DELETE FROM cell_features"))
            con.execute(text("""INSERT INTO cell_features (h3, features, cuisine_affinity, activity_by_daypart, traffic_source,
                                rent_source, rent_resolution, rent_confidence, source, resolution)
                                SELECT h3, features::jsonb, cuisine_affinity::jsonb, activity_by_daypart::jsonb, traffic_source,
                                rent_source, rent_resolution, rent_confidence, source::jsonb, resolution::jsonb
                                FROM cell_features_stage"""))
            con.execute(text("DROP TABLE cell_features_stage"))
    print(f"cell_features: {len(df)} cells x {len(NUMERIC)} numeric columns (+pct)")


if __name__ == "__main__":
    main()
