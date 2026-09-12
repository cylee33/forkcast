"""OSM (Overpass) anchors, parking, shops, suppliers, main roads + PRT GTFS trips → per-cell access features."""
import json
import zipfile

import h3
import numpy as np
import pandas as pd
import requests

from ingest import common

OVERPASS = "https://overpass-api.de/api/interpreter"
GTFS_URL = "https://www.rideprt.org/developerresources/GTFS.zip"
S, W, N, E = common.BBOX
BB = f"({S},{W},{N},{E})"

ANCHORS = ["university", "school", "office", "hospital", "hotel", "bar", "nightclub", "mall", "cinema",
           "stadium", "park", "attraction", "transit_station"]
SUPPLIERS = ["wholesale", "supermarket", "seafood", "butcher", "greengrocer", "asian_grocer", "italian_grocer"]
DIST_ANCHORS = ["university", "hospital", "transit_station", "stadium"]

QUERIES = {
    "pois": f"""[out:json][timeout:180];(
      nwr["amenity"~"^(university|college|school|hospital|bar|pub|nightclub|cinema|theatre|parking|cafe|restaurant|fast_food|marketplace)$"]{BB};
      nwr["tourism"~"^(hotel|attraction|museum|zoo)$"]{BB};
      nwr["leisure"~"^(park|stadium|sports_centre)$"]{BB};
      nwr["shop"]{BB};
      nwr["office"]{BB};
      nwr["railway"="station"]{BB};
      nwr["public_transport"="station"]{BB};
    );out center tags;""",
    "roads": f"""[out:json][timeout:180];(way["highway"~"^(primary|secondary|tertiary)$"]{BB};);out geom;""",
}


def overpass(name: str) -> dict:
    path = common.RAW / f"osm/{name}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.post(OVERPASS, data={"data": QUERIES[name]}, timeout=300,
                           headers={"User-Agent": "forkcast/0.1 (hackathon research; contact cylee@andrew.cmu.edu)"})
        r.raise_for_status()
        path.write_text(r.text)
    return json.loads(path.read_text())


def classify(t: dict) -> str | None:
    a, shop = t.get("amenity"), t.get("shop")
    if a in ("university", "college"):
        return "university"
    if a == "school":
        return "school"
    if a == "hospital":
        return "hospital"
    if a in ("bar", "pub"):
        return "bar"
    if a == "nightclub":
        return "nightclub"
    if a in ("cinema", "theatre"):
        return "cinema"
    if a == "parking":
        return "parking"
    if t.get("tourism") == "hotel":
        return "hotel"
    if t.get("tourism") in ("attraction", "museum", "zoo"):
        return "attraction"
    if t.get("leisure") == "park":
        return "park"
    if t.get("leisure") in ("stadium", "sports_centre"):
        return "stadium"
    if t.get("railway") == "station" or t.get("public_transport") == "station":
        return "transit_station"
    if shop == "mall":
        return "mall"
    if shop == "wholesale":
        return "wholesale"
    if shop == "supermarket":
        cu, nm = (t.get("cuisine") or "").lower(), (t.get("name") or "").lower()
        if any(k in cu or k in nm for k in ("asian", "korean", "chinese", "japanese", "indian", "oriental")):
            return "asian_grocer"
        if "italian" in cu or "italian" in nm:
            return "italian_grocer"
        return "supermarket"
    if shop == "seafood":
        return "seafood"
    if shop == "butcher":
        return "butcher"
    if shop == "greengrocer":
        return "greengrocer"
    if shop:
        return "shop"
    if t.get("office"):
        return "office"
    if a in ("cafe", "restaurant", "fast_food", "marketplace"):
        return "amenity_other"
    return None


def pois_df(data: dict) -> pd.DataFrame:
    rows = []
    for el in data["elements"]:
        t = el.get("tags", {})
        kind = classify(t)
        if not kind:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        rows.append({"osm_id": el["id"], "name": t.get("name", ""), "kind": kind, "lat": lat, "lng": lng})
    return common.points_to_h3(pd.DataFrame(rows))


def roads_h3(data: dict) -> set:
    out = set()
    for el in data["elements"]:
        for p in el.get("geometry", []):
            out.add(h3.latlng_to_cell(p["lat"], p["lon"], common.H3_RES))
    return out


def gtfs_trips_per_cell() -> pd.Series:
    path = common.RAW / "gtfs/prt.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(GTFS_URL, timeout=300).content)
    z = zipfile.ZipFile(path)
    stops = pd.read_csv(z.open("stops.txt"), dtype={"stop_id": str})
    st = pd.read_csv(z.open("stop_times.txt"), dtype={"stop_id": str}, usecols=["stop_id"])
    per_stop = st.groupby("stop_id").size().rename("trips")
    stops = stops.merge(per_stop, left_on="stop_id", right_index=True, how="inner")
    stops = common.points_to_h3(stops, lat="stop_lat", lng="stop_lon")
    return stops.groupby("h3")["trips"].sum() / 7.0  # feed covers a week of service ids; per-day proxy


def _haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _nearest_km(cells: pd.DataFrame, pts: pd.DataFrame) -> np.ndarray:
    if pts.empty:
        return np.full(len(cells), 25.0)
    d = _haversine_km(cells.lat.values[:, None], cells.lng.values[:, None], pts.lat.values[None, :], pts.lng.values[None, :])
    return d.min(axis=1)


def cell_metrics(pois: pd.DataFrame, cells: pd.DataFrame, roads_h3: set, gtfs_trips: pd.Series) -> pd.DataFrame:
    out = cells[["h3"]].copy().set_index("h3")
    counts = pois.groupby(["h3", "kind"]).size().unstack(fill_value=0)
    for k in ANCHORS:
        s = counts[k] if k in counts else pd.Series(0.0, index=counts.index)
        out[f"anchor_{k}"] = common.disk_sum(s.reindex(out.index, fill_value=0.0), 2)
    for k in DIST_ANCHORS:
        out[f"dist_to_{k}_km"] = _nearest_km(cells, pois[pois.kind == k])
    for k in SUPPLIERS:
        out[f"dist_to_{k}_km"] = _nearest_km(cells, pois[pois.kind == k])
    park = counts["parking"] if "parking" in counts else pd.Series(0.0, index=counts.index)
    out["parking_lots"] = common.disk_sum(park.reindex(out.index, fill_value=0.0), 1)
    walk = pois[pois.kind.isin(["shop", "amenity_other", "bar", "cinema", "mall", "attraction"])].groupby("h3").size()
    out["walkable_poi_density"] = common.disk_sum(walk.reindex(out.index, fill_value=0.0), 2)
    out["poi_density"] = pois.groupby("h3").size().reindex(out.index, fill_value=0.0)
    out["main_road_frontage"] = [1.0 if h in roads_h3 else 0.0 for h in out.index]
    out["transit_daily_trips"] = common.disk_sum(gtfs_trips.reindex(out.index, fill_value=0.0), 1)
    return out.reset_index()


def main():
    args = common.cli(__doc__)
    pois = pois_df(overpass("pois"))
    manual_path = common.ROOT / "data/suppliers_manual.csv"
    if manual_path.exists():
        manual = common.points_to_h3(pd.read_csv(manual_path))
        manual["id"] = "manual:" + manual.index.astype(str)
        manual["source"] = "manual"
        manual["osm_id"] = -1
        manual["kind"] = manual["supplier_type"]
        pois = pd.concat([pois, manual[["osm_id", "name", "kind", "lat", "lng", "h3"]]], ignore_index=True)
    else:
        print(f"note: {manual_path} not found, skipping manual suppliers")
    roads = roads_h3(overpass("roads"))
    trips = gtfs_trips_per_cell()
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    common.save(pois, "osm_pois")
    common.save(cell_metrics(pois, cells, roads, trips), "osm_cells")
    sup = pois[pois.kind.isin(SUPPLIERS)].rename(columns={"kind": "supplier_type"})
    sup["id"] = "osm:" + sup.osm_id.astype(str)
    sup["source"] = "osm"
    common.save(sup[["id", "name", "supplier_type", "lat", "lng", "h3", "source"]], "suppliers")
    if not args.no_db:
        common.write_table(common.load("suppliers"), "suppliers")
    print(f"osm: {len(pois)} pois, {pois.kind.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
