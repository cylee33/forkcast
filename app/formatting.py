"""Pure helpers for formatting and shaping `RecommendResponse` data for display.

Kept free of Streamlit/pydeck imports so they can be unit tested directly (see
`app/test_app.py`) without a running app. The one rule every function here exists to
enforce: an unknown value (`None`) must never be displayed or plotted as if it were a
measured zero.
"""

from __future__ import annotations

from typing import Any

NO_DATA = "no data"

SUBSCORE_KEYS = ["D", "C", "T", "A", "S_spend", "K", "Sup"]

SUBSCORE_LABELS: dict[str, str] = {
    "D": "Demand",
    "C": "Competition",
    "T": "Traffic",
    "A": "Access",
    "S_spend": "Spending",
    "K": "Cost",
    "Sup": "Supply",
}

# Sub-scores that are known to be derived from a proxy rather than a direct measurement
# right now. Shown as a fixed disclosure next to the sub-score, not inferred per-request,
# since the response contract carries no per-cell provenance flag for it.
PROXY_SUBSCORES = {"T"}

# Sequential ramp for the opportunity grid, read on a dark basemap: deep blue at the
# bottom rising through teal to amber at the top. Two hues, one direction, so the ramp
# reads as "colder -> hotter" and never as a red/green pass-fail.
SCORE_COLOR_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0, (30, 58, 95)),
    (35, (33, 118, 150)),
    (60, (46, 196, 182)),
    (85, (255, 209, 102)),
    (100, (255, 171, 64)),
]

# Flat slate grey, off the ramp entirely: "no data" must never read as "low score".
NULL_COLOR: tuple[int, int, int, int] = (58, 65, 80, 110)


def format_score(value: float | None, decimals: int = 0) -> str:
    """Format a 0-100 sub-score for display. `None` renders as the literal 'no data'
    string rather than being coerced to a number."""
    if value is None:
        return NO_DATA
    return f"{value:.{decimals}f}"


def score_bar_fraction(value: float | None) -> float | None:
    """Fraction (0-1) for a bar widget. `None` stays `None` - callers must branch on it
    and render an explicit "no data" state instead of defaulting to an empty/zero bar."""
    if value is None:
        return None
    return max(0.0, min(1.0, value / 100.0))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def color_for_score(
    value: float | None,
    stops: list[tuple[float, tuple[int, int, int]]] = SCORE_COLOR_STOPS,
    null_color: tuple[int, int, int, int] = NULL_COLOR,
) -> tuple[int, int, int, int]:
    """Map a 0-100 score to an RGBA color for the hex map / bars. `None` returns a
    distinct translucent grey instead of interpolating to the bottom of the scale."""
    if value is None:
        return null_color
    v = max(0.0, min(100.0, float(value)))
    for (lo_pct, lo_c), (hi_pct, hi_c) in zip(stops, stops[1:]):
        if lo_pct <= v <= hi_pct:
            t = 0.0 if hi_pct == lo_pct else (v - lo_pct) / (hi_pct - lo_pct)
            return (
                round(_lerp(lo_c[0], hi_c[0], t)),
                round(_lerp(lo_c[1], hi_c[1], t)),
                round(_lerp(lo_c[2], hi_c[2], t)),
                210,
            )
    last = stops[-1][1]
    return (last[0], last[1], last[2], 210)


def format_rent(est_rent_psf_yr: float | None, rent_confidence: float | None) -> str:
    """Rent is unknown for every cell today (no rent data has been collected yet). Say
    so plainly rather than implying $0/sqft."""
    if est_rent_psf_yr is None or not rent_confidence:
        return "Rent: unknown (no data yet)"
    return f"${est_rent_psf_yr:.0f}/sqft/yr (confidence {rent_confidence:.0%})"


def format_backtest_rho(rho: float | None, n: int | None = None) -> str:
    """`backtest_rho` is `None` until the backtest has been run at least once."""
    if rho is None:
        return "Backtest not yet run"
    suffix = f" (n={n})" if n else ""
    return f"ρ = {rho:.2f}{suffix}"


def rank_zones(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Zones ranked by `total` descending, highest opportunity first."""
    return sorted(zones, key=lambda z: z.get("total", float("-inf")), reverse=True)


def build_hex_records(cells_geojson: dict[str, Any], metric_key: str = "total") -> list[dict[str, Any]]:
    """Flatten a `cells` FeatureCollection into per-hex records for `pydeck.H3HexagonLayer`
    (which resolves geometry from the `h3` id itself, so no geometry column is needed),
    with a pre-computed fill color and a tooltip-safe display string for every sub-score
    so a null never reaches the map as an interpolated color or a raw `None` in text."""
    records = []
    for feature in cells_geojson.get("features", []):
        props = feature.get("properties", {})
        metric_value = props.get(metric_key)
        record = dict(props)
        record["fill_color"] = list(color_for_score(metric_value))
        record["total_display"] = format_score(props.get("total"))
        for key in SUBSCORE_KEYS:
            record[f"{key}_display"] = format_score(props.get(key))
        records.append(record)
    return records


def diff_profile(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Human-readable list of fields that changed between two `ConceptProfile` dicts, for
    the refine bar's "what changed" display. Only reports fields present in `after`."""
    lines = []
    for key, new_value in after.items():
        old_value = before.get(key)
        if old_value != new_value:
            lines.append(f"{key}: {old_value!r} → {new_value!r}")
    return lines


def apply_profile_edits(profile: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    """Return a new profile dict with `edits` merged in, leaving `profile` untouched."""
    merged = dict(profile)
    merged.update(edits)
    return merged


def apply_refine_response(
    old_profile: dict[str, Any], response: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Reconcile a `/api/concept/refine` response into `(new_profile, diff_lines)`.

    Accepts either `{"profile": {...}, "diff": [...]}` or a bare patched-profile dict
    (the request shape isn't a frozen contract yet); when the response carries no
    explicit diff, one is computed locally so the refine bar can always show what changed.
    """
    new_profile = response.get("profile", response) if "profile" in response else response
    diff_lines = response.get("diff")
    if not isinstance(diff_lines, list):
        diff_lines = diff_profile(old_profile, new_profile)
    return new_profile, diff_lines


def competitor_caveat() -> str:
    """Static disclosure shown near competitor panels: cuisine is identified for only
    ~49% of open places, so an empty or short competitor list may reflect missing
    identification rather than an actual gap. Never padded with filler rows."""
    return (
        "Competitor matching is limited: cuisine is identified for only ~49% of open "
        "places, so these lists may be thinner than the real market."
    )


def traffic_provenance_note() -> str:
    """Static disclosure for the Traffic sub-score: every cell's traffic signal is
    currently derived from a proxy (anchors, transit, workers, POI density), not
    measured foot traffic."""
    return "Traffic is derived from a proxy signal (anchors, transit, workers), not measured foot traffic."


# Rectangular tiles. H3 res-9 cells are hexagons, but the map draws each cell as a
# rectangle centred on the cell so the grid reads as a pixel raster. Hex centres sit
# ~302 m apart within a row and rows are ~262 m apart, so 290 x 250 m tiles leave a
# hairline gap and never stack.
TILE_W_M = 290.0
TILE_H_M = 250.0


def rect_polygon(lat: float, lng: float, w_m: float = TILE_W_M, h_m: float = TILE_H_M) -> list[list[float]]:
    """Closed [lng, lat] ring for a w x h metre rectangle centred on (lat, lng)."""
    import math

    dlat = (h_m / 2) / 111_320.0
    dlng = (w_m / 2) / (111_320.0 * math.cos(math.radians(lat)))
    return [
        [lng - dlng, lat - dlat],
        [lng + dlng, lat - dlat],
        [lng + dlng, lat + dlat],
        [lng - dlng, lat + dlat],
        [lng - dlng, lat - dlat],
    ]


def build_grid_records(cells_geojson: dict[str, Any], metric_key: str = "total") -> list[dict[str, Any]]:
    """`build_hex_records` plus a `polygon` ring per cell for `pydeck.PolygonLayer`."""
    import h3

    records = build_hex_records(cells_geojson, metric_key)
    for record in records:
        lat, lng = h3.cell_to_latlng(record["h3"])
        record["polygon"] = rect_polygon(lat, lng)
    return records
