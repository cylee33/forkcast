"""Geographic helpers shared by every sub-score: haversine distance and H3 candidate
generation. No network calls, no per-cell Python loops -- everything here is vectorized
NumPy or a single h3.grid_disk call.
"""
import math

import h3
import numpy as np

H3_RES = 9
EARTH_RADIUS_KM = 6371.0
MI_TO_KM = 1.60934

# Empirically, the max distance to the edge of h3.grid_disk(center, k) at res 9 grows at
# about 2x the average hex edge length per ring (measured: k=10 -> 3.6km, k=20 -> 7.2km,
# edge_km=0.174), not 1x -- so this is the calibrated conversion, not the naive one.
EDGE_KM = h3.average_hexagon_edge_length(H3_RES, unit="km")
KM_PER_RING = 2.0 * EDGE_KM

CATCHMENT_SPEED_KMH = {"walk": 5.0, "transit": 15.0, "drive": 30.0}
# lambda for Competition's distance decay (§5.3), meters converted to km.
COMP_LAMBDA_KM = {"walk": 0.4, "transit": 0.8, "drive": 2.0}


def haversine_km(lat1, lng1, lat2, lng2):
    """Vectorized great-circle distance in km; broadcasts over any combination of
    scalars/arrays (e.g. targets[:, None] against sources[None, :])."""
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lng1 = np.radians(np.asarray(lng1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    lng2 = np.radians(np.asarray(lng2, dtype=float))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _ring_k_for_radius(radius_km: float, slack_rings: int = 2) -> int:
    return max(1, math.ceil(radius_km / KM_PER_RING) + slack_rings)


def cells_within_radius(center: tuple[float, float], radius_mi: float,
                         available: set[str]) -> list[str]:
    """h3 res-9 cells within `radius_mi` of `center`, restricted to cells present in
    `available` (i.e. cells the feature store actually has a row for)."""
    lat, lng = center
    radius_km = radius_mi * MI_TO_KM
    center_h3 = h3.latlng_to_cell(lat, lng, H3_RES)
    k = _ring_k_for_radius(radius_km)
    ring = [c for c in h3.grid_disk(center_h3, k) if c in available]
    if not ring:
        return []
    lats = np.array([h3.cell_to_latlng(c)[0] for c in ring])
    lngs = np.array([h3.cell_to_latlng(c)[1] for c in ring])
    dists = haversine_km(lat, lng, lats, lngs)
    return [c for c, d in zip(ring, dists) if d <= radius_km]


def halo_cells(center: tuple[float, float], radius_mi: float, extra_rings: int,
               available: set[str]) -> list[str]:
    """Cells within `radius_mi` plus `extra_rings` additional h3 rings of context, per
    forkcast-proposal.md §5.1's "radius plus grid_disk(3) halo" candidate rule."""
    lat, lng = center
    radius_km = radius_mi * MI_TO_KM
    center_h3 = h3.latlng_to_cell(lat, lng, H3_RES)
    k = _ring_k_for_radius(radius_km) + extra_rings
    return [c for c in h3.grid_disk(center_h3, k) if c in available]
