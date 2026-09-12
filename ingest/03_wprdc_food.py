"""WPRDC Allegheny County food facilities → authoritative restaurant list with open/closed status."""
import json
import os

import pandas as pd
import requests

from ingest import common, taxonomy

API = "https://data.wprdc.org/api/3/action/datastore_search"
COLS = {"id": "id", "name": "facility_name", "status": "status", "desc": "description",
        "lat": "y", "lng": "x", "address": "address", "close_date": "bus_cl_date"}
KEEP_TYPES = ("restaurant", "bar", "tavern", "cafe", "coffee", "bakery", "pizza", "deli", "food truck", "brewery")


def fetch() -> list[dict]:
    path = common.RAW / "wprdc/food_facilities.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    rid, offset, rows = os.environ["WPRDC_FOOD_RESOURCE_ID"], 0, []
    while True:
        r = requests.get(API, params={"resource_id": rid, "limit": 5000, "offset": offset}, timeout=60).json()
        recs = r["result"]["records"]
        rows += recs
        if len(recs) < 5000:
            break
        offset += 5000
    path.write_text(json.dumps(rows))
    return rows


def normalize_rows(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).rename(columns={v: k for k, v in COLS.items()})
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    df = df.dropna(subset=["lat", "lng"])
    df = df[df["desc"].str.lower().str.contains("|".join(KEEP_TYPES), na=False)]
    df["is_open"] = df["close_date"].isna()
    df["provider_id"] = df["id"].astype(str)
    df["id"] = "wprdc:" + df["provider_id"]
    df["provider"] = "wprdc"
    df["source"] = "wprdc"
    df["categories"] = df["desc"].apply(lambda d: [str(d).lower()])
    df["cuisine_key"] = [taxonomy.cuisine_for(n, c) for n, c in zip(df["name"], df["categories"])]
    df = common.points_to_h3(df)
    return df[["id", "provider", "provider_id", "name", "lat", "lng", "h3", "categories",
               "cuisine_key", "is_open", "source", "address"]].reset_index(drop=True)


def main():
    args = common.cli(__doc__)
    df = normalize_rows(fetch())
    if args.limit:
        df = df.head(args.limit)
    common.save(df, "places_wprdc")
    print(f"wprdc: {len(df)} facilities, {df.is_open.sum()} open")


if __name__ == "__main__":
    main()
