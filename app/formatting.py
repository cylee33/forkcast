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

# 5-stop sequential palette (Poor -> Excellent). Blue-grey rising through teal and gold to
# amber - reads on both a light and a dark map basemap and avoids a red/green "stoplight"
# read that would misleadingly imply pass/fail.
SCORE_COLOR_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0, (70, 90, 120)),
    (25, (60, 130, 150)),
    (50, (95, 165, 120)),
    (75, (210, 170, 60)),
    (100, (225, 120, 55)),
]

# Translucent neutral grey: visually distinct from any point on the score ramp above,
# including its low end, so "no data" never reads as "low score".
NULL_COLOR: tuple[int, int, int, int] = (130, 130, 138, 60)


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
