"""Extract prototype data files from the real pipeline outputs + OSM.

Run from repo root:  uv run --with shapely --with pandas --with pyarrow python web/prototype/make_data.py

Writes (all consumed by web/prototype/index.html):
  streets_real.geojson   — real OSM centerlines for the demo commercial corridors
  competitors.json       — real open food places (name/cuisine/rating) from places.parquet
  cellmeta.json          — real pct_students / spending_capacity per fixture h3 cell
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent

# ---------------------------------------------------------------- streets
# name, neighborhood, address-number range, clip bbox (south, west, north, east)
CORRIDORS = [
    ("S Craig Street",  "Oakland",        (280, 480),   (40.4415, -79.9505, 40.4495, -79.9475)),
    ("Forbes Avenue",   "Oakland",        (3600, 4000), (40.4400, -79.9640, 40.4445, -79.9490)),
    ("Walnut Street",   "Shadyside",      (5400, 5880), (40.4500, -79.9390, 40.4525, -79.9290)),
    ("Butler Street",   "Lawrenceville",  (3500, 4700), (40.4630, -79.9680, 40.4690, -79.9540)),
    ("E Carson Street", "South Side",     (1000, 2200), (40.4270, -79.9860, 40.4305, -79.9660)),
    ("Murray Avenue",   "Squirrel Hill",  (1900, 2300), (40.4330, -79.9245, 40.4430, -79.9215)),
    ("Penn Avenue",     "Strip District", (2000, 2900), (40.4490, -79.9820, 40.4560, -79.9680)),
    ("Liberty Avenue",  "Bloomfield",     (4400, 4800), (40.4600, -79.9530, 40.4645, -79.9420)),
]

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

def overpass(query: str):
    import time
    last = None
    for attempt in range(4):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            req = urllib.request.Request(
                url, data=("data=" + urllib.parse.quote(query)).encode(),
                headers={"User-Agent": "forkcast-hackathon/0.1 (team project)"})
            return json.load(urllib.request.urlopen(req, timeout=90))["elements"]
        except Exception as e:  # 504s under load — back off and rotate mirrors
            last = e
            time.sleep(3 * (attempt + 1))
    raise last

def fetch_streets():
    from shapely.geometry import LineString, MultiLineString, mapping
    from shapely.ops import linemerge

    import time
    feats = []
    for name, hood, rng, (s, w, n, e) in CORRIDORS:
        time.sleep(2)
        q = f"""[out:json][timeout:30];
way["highway"]["name"="{name.replace('S Craig Street', 'South Craig Street').replace('E Carson Street', 'East Carson Street')}"]({s},{w},{n},{e});
out geom;"""
        ways = overpass(q)
        if not ways:  # some corridors sign the short form
            q2 = f'[out:json][timeout:30];way["highway"]["name"~"{name}"]({s},{w},{n},{e});out geom;'
            ways = overpass(q2)
        lines = [LineString([(pt["lon"], pt["lat"]) for pt in wy["geometry"]])
                 for wy in ways if len(wy.get("geometry", [])) > 1]
        if not lines:
            print(f"!! no OSM ways for {name} — keep the hand-drawn fallback")
            continue
        merged = linemerge(MultiLineString(lines))
        line = max(merged.geoms, key=lambda g: g.length) if merged.geom_type == "MultiLineString" else merged
        line = line.simplify(0.00004)
        feats.append({"type": "Feature",
                      "properties": {"name": name, "hood": hood, "range": list(rng)},
                      "geometry": mapping(line)})
        print(f"{name}: {len(lines)} segments -> {len(line.coords)} pts")
    json.dump({"type": "FeatureCollection", "features": feats}, open(OUT / "streets_real.geojson", "w"))

# ---------------------------------------------------------------- competitors + cell metadata
def fetch_tables():
    import pandas as pd

    root = OUT.parent.parent
    p = pd.read_parquet(root / "data/processed/places.parquet")
    box = p[(p.lat.between(40.40, 40.48)) & (p.lng.between(-80.02, -79.90)) & (p.is_open == True)]  # noqa: E712
    cols = box[["name", "lat", "lng", "cuisine_key", "price_level", "rating", "reviews"]].copy()
    cols = cols.where(pd.notnull(cols), None)
    json.dump(cols.to_dict("records"), open(OUT / "competitors.json", "w"))
    print("competitors:", len(cols))

    c = pd.read_parquet(root / "data/fixtures/cell_features_sample.parquet")
    meta = {row["h3"]: {
        "students": round(float(row["pct_students"]) * 100, 1) if row["pct_students"] == row["pct_students"] else None,
        "spend": int(row["spending_capacity"]) if row["spending_capacity"] == row["spending_capacity"] else None,
        "restaurants": int(row["restaurants_open"]) if row["restaurants_open"] == row["restaurants_open"] else None,
    } for _, row in c.iterrows()}
    json.dump(meta, open(OUT / "cellmeta.json", "w"))
    print("cellmeta:", len(meta))

if __name__ == "__main__":
    fetch_streets()
    fetch_tables()
