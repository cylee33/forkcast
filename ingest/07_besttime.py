"""BestTime hourly busyness for top POIs → daypart activity per cell; proxy from anchors/transit/workers elsewhere."""
import json
import os

import h3
import numpy as np
import pandas as pd
import requests

from ingest import common

API = "https://besttime.app/api/v1/forecasts"
TOP_N = 500
HOURS = {"morning": range(6, 11), "lunch": range(11, 14), "afternoon": range(14, 17),
         "dinner": range(17, 21), "late_night": list(range(21, 24)) + list(range(0, 3))}
DAYPARTS = list(HOURS) + ["weekend"]
PA_COLS = ["place_id", "daypart", "busyness"]
PA_DTYPES = {"place_id": "object", "daypart": "object", "busyness": "float64"}


def fetch_venue(place_id: str, name: str, address: str | None, lat: float, lng: float) -> list[list[int]] | None:
    path = common.RAW / f"besttime/{place_id.replace(':', '_')}.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.post(API, params={"api_key_private": os.environ["BESTTIME_API_KEY_PRIVATE"],
                                   "venue_name": name, "venue_address": address or f"{lat},{lng} Pittsburgh PA"},
                      timeout=60).json()
    week = [d["day_raw"] for d in r.get("analysis", [])] if r.get("status") == "OK" else None
    path.write_text(json.dumps(week))
    return week


def dayparts_from_hours(week: list[list[int]]) -> dict[str, float]:
    """Per day, the peak busyness within each daypart's hour bucket (a lunch rush at noon
    shouldn't be diluted by quiet hours either side of it); averaged across the week's days.
    Weekend is a plain mean over Sat/Sun (rows 5-6), all hours -- a different kind of signal
    (weekend-vs-weekday overall busyness, not a time-of-day bucket)."""
    arr = np.array(week, dtype=float)  # 7 x 24, Monday first
    out = {k: float(arr[:, list(hrs)].max(axis=1).mean()) for k, hrs in HOURS.items()}
    out["weekend"] = float(arr[5:7].mean())
    return out


def place_activity_frame(rows: list[dict]) -> pd.DataFrame:
    """Build the place_activity frame with a fixed dtype (busyness: float64) whether there are
    rows or not, so the parquet's schema doesn't change shape depending on whether a run had
    real venues (an empty `pd.DataFrame(columns=...)` would otherwise leave every column
    object-typed)."""
    return pd.DataFrame(rows, columns=PA_COLS).astype(PA_DTYPES)


def proxy_activity(cells: pd.DataFrame, osm: pd.DataFrame, lodes: pd.DataFrame) -> pd.DataFrame:
    df = cells[["h3"]].merge(osm, on="h3", how="left").merge(lodes, on="h3", how="left").fillna(0)
    base = (common.pct(df.walkable_poi_density) + common.pct(df.transit_daily_trips)) / 2
    work = common.pct(df.workers_daytime)
    night = common.pct(df.anchor_bar + df.anchor_nightclub)
    out = pd.DataFrame({"h3": df.h3})
    out["activity_morning"] = 0.5 * base + 0.5 * work
    out["activity_lunch"] = 0.4 * base + 0.6 * work
    out["activity_afternoon"] = 0.6 * base + 0.4 * work
    out["activity_dinner"] = 0.7 * base + 0.3 * night
    out["activity_late_night"] = 0.3 * base + 0.7 * night
    out["activity_weekend"] = 0.6 * base + 0.4 * night
    return out


def cells_from_activity(pa: pd.DataFrame, places: pd.DataFrame, cells: pd.DataFrame, proxy: pd.DataFrame) -> pd.DataFrame:
    """Distance-weighted (grid_disk(2), weight 1/(1+ring)) mean of real venue busyness; proxy where no venue within 2 rings."""
    out = proxy.set_index("h3").copy()
    out["traffic_source"] = "proxy"
    if pa.empty:
        return out.reset_index()
    wide = pa.pivot(index="place_id", columns="daypart", values="busyness")
    wide = wide.merge(places[["id", "h3"]].set_index("id"), left_index=True, right_index=True)
    by_cell = wide.groupby("h3").mean()
    real = {}
    for h in cells.h3:
        num, den = np.zeros(len(DAYPARTS)), 0.0
        for ring, cs in enumerate(h3.grid_ring(h, k) for k in range(3)):
            for c in cs:
                if c in by_cell.index:
                    w = 1.0 / (1 + ring)
                    num += w * by_cell.loc[c, DAYPARTS].values
                    den += w
        if den > 0:
            real[h] = num / den
    for h, v in real.items():
        out.loc[h, [f"activity_{d}" for d in DAYPARTS]] = v
        out.loc[h, "traffic_source"] = "real"
    return out.reset_index()


def write_place_activity_db(pa: pd.DataFrame) -> None:
    """Stage then move into the real `place_activity` table, so its declared PK/FK constraints
    survive the write instead of being dropped by write_table's default if_exists='replace'."""
    from sqlalchemy import text
    common.write_table(pa, "place_activity_stage")
    with common.engine().begin() as con:
        con.execute(text("DELETE FROM place_activity"))
        con.execute(text("""INSERT INTO place_activity (place_id, daypart, busyness)
                            SELECT place_id, daypart, busyness FROM place_activity_stage"""))
        con.execute(text("DROP TABLE place_activity_stage"))


def main():
    args = common.cli(__doc__)
    places = common.load("places")
    cells = common.load_cells()
    proxy = proxy_activity(cells, common.load("osm_cells"), common.load("lodes"))

    api_key = os.environ.get("BESTTIME_API_KEY_PRIVATE")
    if not api_key:
        print("besttime: BESTTIME_API_KEY_PRIVATE not set, writing proxy only")
        pa = place_activity_frame([])
    else:
        top = places[places.is_open & places.reviews.notna()].sort_values("reviews", ascending=False)
        if args.limit is not None:
            top = top.head(args.limit)
        else:
            top = top.head(TOP_N)
        rows = []
        for _, p in top.iterrows():
            week = fetch_venue(p.id, p.name, p.get("address"), p.lat, p.lng)
            if week and len(week) == 7:
                rows += [{"place_id": p.id, "daypart": d, "busyness": v} for d, v in dayparts_from_hours(week).items()]
        pa = place_activity_frame(rows)

    common.save(pa, "place_activity")
    common.save(cells_from_activity(pa, places, cells, proxy), "activity_cells")
    if not args.no_db and len(pa):
        write_place_activity_db(pa)
    print(f"besttime: {pa.place_id.nunique()} venues with real data")


if __name__ == "__main__":
    main()
