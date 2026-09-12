"""POC: real street-bounded block polygons for Oakland, Pittsburgh via Overpass + shapely."""
import json, urllib.request

BBOX = (40.425, -79.975, 40.455, -79.935)  # south, west, north, east — Oakland + Craig St
q = f"""[out:json][timeout:30];
way["highway"~"^(primary|secondary|tertiary|residential|unclassified|living_street|pedestrian)$"]
  ({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out geom;"""
req = urllib.request.Request(
    "https://overpass-api.de/api/interpreter",
    data=("data=" + urllib.parse.quote(q)).encode(),
    headers={"User-Agent": "forkcast-hackathon-poc/0.1 (contact: team)"})
ways = json.load(urllib.request.urlopen(req, timeout=60))["elements"]
print("ways:", len(ways))

from shapely.geometry import LineString, mapping
from shapely.ops import unary_union, polygonize

lines = [LineString([(n["lon"], n["lat"]) for n in w["geometry"]]) for w in ways if len(w.get("geometry", [])) > 1]
merged = unary_union(lines)          # nodes lines at intersections
blocks = list(polygonize(merged))
print("raw blocks:", len(blocks))

# filters: drop slivers and mega-blocks (campus/park)
keep = [b for b in blocks if 1500 < b.area * (111320 ** 2) * 0.75 < 120000]  # ~m^2 approx
print("kept blocks:", len(keep))

fc = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"i": i}, "geometry": mapping(b.simplify(0.00003))}
    for i, b in enumerate(keep)]}
out = "/Users/seobeomjin/Desktop/forkcast/web/prototype/blocks_oakland.geojson"
json.dump(fc, open(out, "w"))
import os; print("wrote", out, os.path.getsize(out) // 1024, "KB")
