"""Scoring engine entry points: `analyze()` (forward mode, §5.11), `score_cells()` (the
per-cell scorer reused by reverse mode) and `load_features()` (cached cell_features.parquet).

Sub-score scale conventions (forkcast-proposal.md §5.4):
  D, T, A, S_spend -- percentile-ranked (0-100) across the scored set (see normalize.pct).
  K, Sup, C        -- already final 0-100 scores by their own formulas; not re-percentiled.
  K                -- always None right now: est_rent_psf_yr is NULL on every cell (D19).
"""
import pathlib
import uuid

import h3
import numpy as np
import pandas as pd

from api.models import SUBSCORE_KEYS
from api.scoring import access, competition, confidence, cost, demand, geo, spending, supply, traffic
from api.scoring import weights as weights_mod
from api.scoring import zones as zones_mod
from api.scoring.normalize import pct

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROC = ROOT / "data/processed"

HALO_RINGS = 3
ZONE_MAX_ANCHOR_KM = 3.0
NEARBY_COMPETITOR_MAX_M = 5000.0
ANCHOR_KINDS = {
    "university", "school", "office", "hospital", "hotel", "bar", "nightclub", "mall",
    "cinema", "stadium", "park", "attraction", "transit_station",
}

_FEATURES_CACHE: pd.DataFrame | None = None
_WORKING_CACHE: pd.DataFrame | None = None
_PLACES_CACHE: pd.DataFrame | None = None
_EMBEDDINGS_CACHE: pd.DataFrame | None = None
_OSM_CACHE: pd.DataFrame | None = None


def load_features() -> pd.DataFrame:
    """Cached load of data/processed/cell_features.parquet, indexed by h3 (h3 also kept
    as a regular column so callers can do `features["h3"]`)."""
    global _FEATURES_CACHE
    if _FEATURES_CACHE is None:
        df = pd.read_parquet(PROC / "cell_features.parquet")
        _FEATURES_CACHE = df.set_index("h3", drop=False)
    return _FEATURES_CACHE


def _working_frame() -> pd.DataFrame:
    """load_features() joined with geo_cells' lat/lng, for internal distance math. Not the
    public contract -- load_features() itself stays pure cell_features.parquet content."""
    global _WORKING_CACHE
    if _WORKING_CACHE is None:
        feats = load_features()
        geo_cells = pd.read_parquet(PROC / "geo_cells.parquet").set_index("h3")[["lat", "lng"]]
        _WORKING_CACHE = feats.join(geo_cells, how="left")
    return _WORKING_CACHE


def _load_places() -> pd.DataFrame:
    global _PLACES_CACHE
    if _PLACES_CACHE is None:
        _PLACES_CACHE = pd.read_parquet(PROC / "places.parquet").set_index("id", drop=False)
    return _PLACES_CACHE


def _load_embeddings() -> pd.DataFrame:
    global _EMBEDDINGS_CACHE
    if _EMBEDDINGS_CACHE is None:
        _EMBEDDINGS_CACHE = pd.read_parquet(PROC / "place_embeddings.parquet").set_index("id")
    return _EMBEDDINGS_CACHE


def _load_osm_pois() -> pd.DataFrame:
    global _OSM_CACHE
    if _OSM_CACHE is None:
        _OSM_CACHE = pd.read_parquet(PROC / "osm_pois.parquet")
    return _OSM_CACHE


def available_subscores(features: pd.DataFrame) -> set[str]:
    """Which of the 7 sub-scores currently have underlying data at all (column-level, not
    per-row). K is excluded unless est_rent_psf_yr has at least one non-null value."""
    avail = {"D", "C", "T", "A", "S_spend", "Sup"}
    if "est_rent_psf_yr" in features.columns and features["est_rent_psf_yr"].notna().any():
        avail.add("K")
    return avail


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def score_cells(profile, h3s: list[str], weights: dict[str, float]) -> pd.DataFrame:
    """Score every h3 in `h3s` for `profile`. Index: h3. Columns: the 7 subscore keys +
    "total" + "confidence" (+ "gap_flag", used by reverse mode's gap bonus).

    Population/competitor aggregation always reaches into the full loaded feature/place
    tables regardless of what subset of `h3s` is requested, so this is correct even when a
    caller (e.g. reverse mode) passes a small ad-hoc list with no halo of its own."""
    features = _working_frame()
    targets = [h for h in dict.fromkeys(h3s) if h in features.index]
    empty_cols = SUBSCORE_KEYS + ["total", "confidence", "gap_flag"]
    if not targets:
        return pd.DataFrame(columns=empty_cols).set_index(pd.Index([], name="h3"))

    tf = features.loc[targets]

    demand_raw = demand.raw_demand(profile, features, targets)
    places = _load_places()
    embeddings = _load_embeddings()
    open_places = places[places["is_open"]]
    comp_raw, cluster_raw, _sim = competition.comp_and_cluster(
        profile, open_places, embeddings, features, targets)

    d_pct = pct(demand_raw)
    c_pct = pct(comp_raw)
    cluster_pct = pct(cluster_raw)
    # Saturation normalized to [-1, 1] (pct's are 0-100) before the sigmoid -- see
    # competition.py's module docstring: at raw 0-100 scale, 3*Saturation would saturate
    # the sigmoid to a near-binary 0/100 output for almost every cell.
    saturation = (c_pct - d_pct) / 100.0
    C = 100.0 * (1.0 - _sigmoid(3.0 * saturation)) + 15.0 * (cluster_pct / 100.0) * (1.0 - c_pct / 100.0)
    C = C.clip(0.0, 100.0)

    D = pct(np.log1p(demand_raw.clip(lower=0.0)))
    T = pct(traffic.raw(profile, tf))
    A = pct(access.raw(profile, tf))
    S = pct(spending.raw_s_spend(profile, tf))
    K = cost.raw(profile, tf)
    Sup = supply.raw(profile, tf)

    sub = pd.DataFrame({"D": D, "C": C, "T": T, "A": A, "S_spend": S, "K": K, "Sup": Sup}, index=targets)

    w = pd.Series({k: v for k, v in weights.items() if k in SUBSCORE_KEYS})
    if len(w):
        contrib = sub[w.index].mul(w, axis=1)
        # a subscore that's NaN for this cell (K, structurally; occasionally Sup if the
        # concept names an untracked supplier type) contributes 0 rather than propagating
        # NaN into total -- defensive even against a caller passing an "available" set
        # that doesn't match reality (e.g. marking K available when it isn't).
        contrib = contrib.where(sub[w.index].notna(), 0.0)
        total = contrib.sum(axis=1)
    else:
        total = pd.Series(0.0, index=targets)

    conf = confidence.compute(tf, sub)
    gap_flag = (D > 60.0) & (comp_raw < 1e-6)

    out = sub.copy()
    out["total"] = total
    out["confidence"] = conf
    out["gap_flag"] = gap_flag
    out.index.name = "h3"
    return out


def _zone_name(best_h3: str, osm: pd.DataFrame, zone_id: int) -> str:
    anchors = _nearby_anchors(best_h3, osm, limit=1, max_km=ZONE_MAX_ANCHOR_KM)
    if anchors:
        return f"Near {anchors[0]['name']}"
    lat, lng = h3.cell_to_latlng(best_h3)
    return f"Zone {zone_id} ({lat:.3f}, {lng:.3f})"


def _nearby_anchors(best_h3: str, osm: pd.DataFrame, limit: int = 5,
                     max_km: float = ZONE_MAX_ANCHOR_KM) -> list[dict]:
    lat, lng = h3.cell_to_latlng(best_h3)
    pts = osm[osm["kind"].isin(ANCHOR_KINDS)]
    if pts.empty:
        return []
    dist_km = geo.haversine_km(lat, lng, pts["lat"].to_numpy(), pts["lng"].to_numpy())
    df = pts.assign(dist_km=dist_km)
    df = df[df["dist_km"] <= max_km].sort_values("dist_km").head(limit)
    return [{"name": r.name, "type": r.kind, "distance_m": float(r.dist_km * 1000.0)}
            for r in df.itertuples()]


def _nearby_competitors(best_h3: str, profile, places: pd.DataFrame,
                         embeddings: pd.DataFrame, limit: int = 5) -> tuple[list[dict], list[dict]]:
    open_places = places[places["is_open"]]
    if open_places.empty:
        return [], []
    sim = competition.blended_similarity(profile, open_places, embeddings)
    lat, lng = h3.cell_to_latlng(best_h3)
    dist_m = geo.haversine_km(lat, lng, open_places["lat"].to_numpy(),
                               open_places["lng"].to_numpy()) * 1000.0
    df = open_places.assign(sim=sim.to_numpy(), dist_m=dist_m)

    def to_records(d: pd.DataFrame) -> list[dict]:
        recs = []
        for r in d.itertuples():
            recs.append({
                "id": r.id, "name": r.name, "distance_m": float(r.dist_m),
                "similarity": float(r.sim),
                "rating": None if pd.isna(r.rating) else float(r.rating),
                "reviews": None if pd.isna(r.reviews) else int(r.reviews),
            })
        return recs

    # "Nearby" per §5.11: prefer competitors within a reasonable radius of the zone before
    # ranking by similarity, so a rare cuisine doesn't surface a same-cuisine place on the
    # other side of the county as the zone's "nearby" competitor. Falls back to
    # county-wide if nothing matches within that radius (still disclosed via distance_m).
    near = df[df["dist_m"] <= NEARBY_COMPETITOR_MAX_M]
    pool = near if not near.empty else df

    direct = pool[pool["sim"] >= competition.DIRECT_SIM].sort_values(
        ["sim", "dist_m"], ascending=[False, True]).head(limit)
    indirect = pool[(pool["sim"] >= competition.SIM_THRESHOLD) & (pool["sim"] < competition.DIRECT_SIM)]
    indirect = indirect.sort_values(["sim", "dist_m"], ascending=[False, True]).head(limit)
    return to_records(direct), to_records(indirect)


def _enrich_zone(zd: dict, profile, features: pd.DataFrame, places: pd.DataFrame,
                  embeddings: pd.DataFrame, osm: pd.DataFrame) -> dict:
    best_h3 = zd["best_h3"]
    subs = {k: v for k, v in zd["subscores"].items() if v is not None}
    ranked = sorted(subs.items(), key=lambda kv: -kv[1])
    drivers = [f"{k} {v:.0f}" for k, v in ranked[:3]]
    risks = [f"{k} {v:.0f}" for k, v in ranked[-2:][::-1]]

    d_pct = subs.get("D", 0.0)
    c_pct = subs.get("C", 0.0)
    competitors_direct, competitors_indirect = _nearby_competitors(best_h3, profile, places, embeddings)
    anchors = _nearby_anchors(best_h3, osm)
    row = features.loc[best_h3]

    return {
        "zone_id": zd["zone_id"],
        "name": _zone_name(best_h3, osm, zd["zone_id"]),
        "total": zd["total"],
        "best_h3": best_h3,
        "subscores": zd["subscores"],
        "confidence": zd["confidence"],
        "drivers": drivers[:3],
        "risks": risks[:2],
        "gap": {"demand": float(d_pct), "supply": float(c_pct), "gap": float(d_pct - c_pct)},
        "gap_flag": bool(d_pct > 60.0 and c_pct < 1e-6),
        "competitors_direct": competitors_direct,
        "competitors_indirect": competitors_indirect,
        "anchors": anchors,
        "est_rent_psf_yr": None if pd.isna(row["est_rent_psf_yr"]) else float(row["est_rent_psf_yr"]),
        "rent_confidence": None if pd.isna(row["rent_confidence"]) else float(row["rent_confidence"]),
    }


def _to_geojson(scored: pd.DataFrame, zone_dicts: list[dict]) -> dict:
    zone_of: dict[str, int] = {}
    for zd in zone_dicts:
        for h in zd["h3_cells"]:
            zone_of[h] = zd["zone_id"]

    features = []
    for h, row in scored.iterrows():
        boundary = h3.cell_to_boundary(h)
        coords = [[lng, lat] for lat, lng in boundary]
        coords.append(coords[0])
        props = {"h3": h, "total": float(row["total"]), "confidence": float(row["confidence"]),
                  "zone_id": zone_of.get(h)}
        for k in SUBSCORE_KEYS:
            v = row[k]
            props[k] = None if pd.isna(v) else float(v)
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]},
                          "properties": props})
    return {"type": "FeatureCollection", "features": features}


def analyze(profile, center: tuple[float, float], radius_mi: float,
            weights: dict[str, float] | None = None) -> dict:
    features = _working_frame()
    available = available_subscores(features)
    proposed = weights if weights is not None else weights_mod.defaults_for(profile.service_format)
    final_weights = weights_mod.validate(proposed, available)

    all_h3 = set(features.index)
    candidates = geo.cells_within_radius(center, radius_mi, all_h3)
    halo_extra = [h for h in geo.halo_cells(center, radius_mi, HALO_RINGS, all_h3)
                  if h not in set(candidates)]

    scored_all = score_cells(profile, candidates + halo_extra, final_weights)
    scored = scored_all.loc[[h for h in candidates if h in scored_all.index]]

    zone_dicts = zones_mod.build_zones(scored, features, top_n=8)
    places = _load_places()
    embeddings = _load_embeddings()
    osm = _load_osm_pois()
    zones = [_enrich_zone(zd, profile, features, places, embeddings, osm) for zd in zone_dicts]

    cells_geojson = _to_geojson(scored, zone_dicts)

    # api/models.py's RecommendResponse.weights is dict[str, float] (no None allowed), so
    # only the validated/available keys are included here -- unlike cells.features[].
    # properties and zone.subscores (typed as nullable dicts) which keep all 7 keys with
    # None for K.
    return {
        "analysis_id": str(uuid.uuid4()),
        "profile": profile.model_dump(),
        "weights": final_weights,
        "cells": cells_geojson,
        "zones": zones,
        "backtest_rho": None,  # §5.9 backtest is run offline, not per-request
    }
