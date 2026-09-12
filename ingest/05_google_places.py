"""Google Places (New) Nearby Search, county-wide on a res-8 grid, field-masked, cached. Merged onto WPRDC rows."""
import json
import os
import re
import time

import h3
import numpy as np
import pandas as pd
import requests

from ingest import common, taxonomy

URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = ("places.id,places.displayName,places.location,places.rating,places.userRatingCount,"
          "places.priceLevel,places.businessStatus,places.types,places.editorialSummary")
TYPES = ["restaurant", "cafe", "bar", "bakery", "meal_takeaway"]
PRICE = {"PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2, "PRICE_LEVEL_EXPENSIVE": 3,
         "PRICE_LEVEL_VERY_EXPENSIVE": 4}


def search_cells() -> list[str]:
    cells = common.load_cells()
    return sorted({h3.cell_to_parent(c, 8) for c in cells.h3})


def _query(lat, lng, radius_m) -> dict:
    """searchNearby (New), retried with exponential backoff on 429/5xx (the free-tier QPS limit is
    tight enough that a county-wide sequential run hits it repeatedly)."""
    body = {"includedTypes": TYPES, "maxResultCount": 20,
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}}}
    headers = {"X-Goog-Api-Key": os.environ["GOOGLE_PLACES_API_KEY"], "X-Goog-FieldMask": FIELDS}
    for attempt in range(6):
        r = requests.post(URL, json=body, timeout=30, headers=headers)
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 5:
                r.raise_for_status()
            time.sleep(2**attempt)
            continue
        r.raise_for_status()
        return r.json()


def fetch_cell(c: str, depth: int = 0) -> list[dict]:
    """Nearby search on the res-8 cell; if 20 results returned (truncated), recurse into res-9 children."""
    path = common.RAW / f"google/{c}.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    lat, lng = h3.cell_to_latlng(c)
    radius = 700 if h3.get_resolution(c) == 8 else 260
    time.sleep(0.3)  # stay under the free-tier QPS cap; _query also retries on 429
    places = _query(lat, lng, radius).get("places", [])
    if len(places) >= 20 and depth < 1:
        places = [p for ch in h3.cell_to_children(c, h3.get_resolution(c) + 1) for p in fetch_cell(ch, depth + 1)]
    path.write_text(json.dumps(places))
    return places


def parse_place(p: dict) -> dict:
    name = p.get("displayName", {}).get("text", "")
    types = p.get("types", [])
    return {"google_id": p["id"], "name": name, "lat": p["location"]["latitude"], "lng": p["location"]["longitude"],
            "rating": p.get("rating"), "reviews": p.get("userRatingCount"),
            "price_level": PRICE.get(p.get("priceLevel")), "google_open": p.get("businessStatus") == "OPERATIONAL",
            "types": types, "summary": (p.get("editorialSummary") or {}).get("text"),
            "cuisine_key": taxonomy.cuisine_for(name, types)}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())[:12]


def match(wprdc: pd.DataFrame, google: pd.DataFrame) -> pd.DataFrame:
    g = google.drop_duplicates("google_id").copy()
    g["_k"] = g.name.map(_norm)
    w = wprdc.copy()
    w["_k"] = w.name.map(_norm)
    m = w.merge(g, on="_k", how="left", suffixes=("", "_g"))
    d = np.hypot((m.lat - m.lat_g) * 111.0, (m.lng - m.lng_g) * 85.0)  # km
    ok = d <= 0.15
    null_cols = ["google_id", "rating", "reviews", "price_level", "google_open", "types", "summary"]
    m[null_cols] = m[null_cols].astype(object)
    m.loc[~ok, null_cols] = None
    m = m.sort_values("reviews", ascending=False).drop_duplicates("id")
    m["source"] = np.where(m.google_id.notna(), "wprdc+google", "wprdc")
    m["is_open"] = m.is_open & m.google_open.map(lambda x: True if pd.isna(x) else bool(x))
    m["cuisine_key"] = m.cuisine_key.fillna(m.get("cuisine_key_g"))
    m["categories"] = [list(c) + (list(t) if isinstance(t, list) else []) for c, t in zip(m.categories, m.types)]
    m["is_chain"] = m.name.map(taxonomy.is_chain)
    m["provider_id"] = m.provider_id.astype(str)
    # Google-only places (no WPRDC match): keep as their own rows
    extra = g[~g.google_id.isin(m.google_id.dropna())].copy()
    extra["id"] = "google:" + extra.google_id
    extra["provider"], extra["provider_id"], extra["source"] = "google", extra.google_id, "google"
    extra["is_open"] = extra.google_open.astype(bool)
    extra["categories"] = extra.types
    extra["is_chain"] = extra.name.map(taxonomy.is_chain)
    extra["address"] = None
    extra = common.points_to_h3(extra)
    cols = ["id", "provider", "provider_id", "name", "lat", "lng", "h3", "categories", "cuisine_key",
            "price_level", "rating", "reviews", "is_chain", "is_open", "source", "summary"]
    return pd.concat([m[cols], extra[cols]], ignore_index=True)


def main():
    args = common.cli(__doc__)
    cells = search_cells()
    if args.limit:
        cells = cells[: args.limit]
    raw = [parse_place(p) for c in cells for p in fetch_cell(c)]
    google = pd.DataFrame(raw)
    common.save(google, "google_raw")
    places = match(common.load("places_wprdc"), google)
    common.save(places, "places")
    if not args.no_db:
        db = places.copy()
        db["categories"] = db.categories.apply(lambda c: "{" + ",".join(f'"{x}"' for x in c) + "}")
        common.write_table(db, "places_stage")
        from sqlalchemy import text
        with common.engine().begin() as con:
            con.execute(text("DELETE FROM place_activity; DELETE FROM places"))
            con.execute(text("""INSERT INTO places (id, provider, provider_id, name, lat, lng, h3, categories, cuisine_key,
                                price_level, rating, reviews, is_chain, is_open, source, summary)
                                SELECT id, provider, provider_id, name, lat, lng, h3, categories::text[], cuisine_key,
                                price_level, rating, reviews, is_chain, is_open, source, summary FROM places_stage"""))
            con.execute(text("DROP TABLE places_stage"))
    print(f"google: {len(google)} raw, places: {len(places)}, matched {(places.source == 'wprdc+google').sum()}")


if __name__ == "__main__":
    main()
