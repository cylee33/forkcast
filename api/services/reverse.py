"""(lat, lng[, sqft, rent]) -> top_n ranked concept archetypes for a pin. Scores every
archetype in api/concept_archetypes.yaml against the cells within ~1 km (proposal §5.8)
using the deterministic scoring engine -- no LLM involved. `score_cells`, `load_features`,
and `weights_validate` are accepted as keyword overrides so tests can inject fakes without
requiring api/scoring (owned by another agent) to exist yet."""
import math
import pathlib

import yaml

from api.models import SUBSCORE_KEYS, ConceptProfile
from api.services.explainer import SUBSCORE_LABELS

ARCHETYPES_PATH = pathlib.Path(__file__).resolve().parents[2] / "api/concept_archetypes.yaml"
H3_RES = 9
H3_RES9_EDGE_M = 174.0  # approximate edge length at resolution 9
RADIUS_M = 1000.0
GAP_BONUS = 15.0
DEFAULT_CONFIDENCE = 0.7


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_archetypes() -> list[ConceptProfile]:
    raw = yaml.safe_load(ARCHETYPES_PATH.read_text())["archetypes"]
    profiles = []
    for entry in raw:
        data = dict(entry)
        data.setdefault("confidence", DEFAULT_CONFIDENCE)
        profiles.append(ConceptProfile(**data))
    return profiles


def _cells_within_radius(lat: float, lng: float, available_h3: set[str],
                          radius_m: float = RADIUS_M) -> list[str]:
    import h3
    center = h3.latlng_to_cell(lat, lng, H3_RES)
    k = max(1, math.ceil(radius_m / H3_RES9_EDGE_M) + 1)
    out = []
    for c in h3.grid_disk(center, k):
        if c not in available_h3:
            continue
        clat, clng = h3.cell_to_latlng(c)
        if _haversine_m(lat, lng, clat, clng) <= radius_m:
            out.append(c)
    return out


def _why(profile: ConceptProfile, subscores: dict[str, float]) -> str:
    ranked = sorted(subscores.items(), key=lambda kv: -kv[1])
    top = ", ".join(f"{SUBSCORE_LABELS.get(k, k)} {v:.0f}" for k, v in ranked[:2])
    return f"{profile.concept_name}: strongest on {top} at the best-scoring cell."


def reverse(lat: float, lng: float, sqft: int | None = None, rent: float | None = None,
            top_n: int = 8, *, score_cells=None, load_features=None, weights_validate=None) -> list[dict]:
    if score_cells is None or load_features is None or weights_validate is None:
        from api.scoring.engine import load_features as _lf, score_cells as _sc
        from api.scoring.weights import validate as _wv
        score_cells = score_cells or _sc
        load_features = load_features or _lf
        weights_validate = weights_validate or _wv

    features = load_features()
    h3s = _cells_within_radius(lat, lng, set(features["h3"]))
    if not h3s:
        return []

    # K (cost fit) needs est_rent_psf_yr; it's NULL on every cell today (docs spec §7:
    # "Rent absent -> K displayed as n/a, K weight set to 0, remaining weights renormalized").
    have_rent = "est_rent_psf_yr" in features.columns and features["est_rent_psf_yr"].notna().any()
    available_keys = set(SUBSCORE_KEYS) if have_rent else set(SUBSCORE_KEYS) - {"K"}
    results = []
    for profile in load_archetypes():
        weights = weights_validate(dict(profile.proposed_weights), available_keys)
        scored = score_cells(profile, h3s, weights)
        if scored is None or len(scored) == 0:
            continue
        best = scored.loc[scored["total"].idxmax()]
        total = float(best["total"])
        gap_flag = bool(best["gap_flag"]) if "gap_flag" in scored.columns else False
        if gap_flag:
            total += GAP_BONUS
        subscores = {k: float(best[k]) for k in SUBSCORE_KEYS if k in scored.columns}
        results.append({
            "archetype": profile.concept_name,
            "concept_name": profile.concept_name,
            "total": total,
            "subscores": subscores,
            "why": _why(profile, subscores),
        })

    results.sort(key=lambda r: -r["total"])
    return results[:top_n]
