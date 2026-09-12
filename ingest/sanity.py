"""Static heatmaps to eyeball the feature store, plus adversarial checks that catch
defects the maps alone would not: a constant column, a zero-inflated column whose
percentile floor has drifted to mid-scale, or a feature whose geography contradicts
known Pittsburgh. Oakland / Downtown / Strip should be hot."""
import h3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ingest import common

COLS = ["pop_total", "median_hh_income", "workers_daytime", "poi_density", "restaurants_open", "activity_dinner",
        "est_rent_psf_yr", "spending_capacity", "transit_daily_trips"]

# Known-dense, known-active Pittsburgh neighborhoods vs. a quiet outer borough.
HOT_SPOTS = {
    "Downtown": (40.4406, -79.9959),
    "Oakland": (40.4443, -79.9539),
    "Shadyside": (40.4526, -79.9319),
    "South Side": (40.4283, -79.9741),
    "Strip District": (40.4514, -79.9797),
}
COLD_SPOT = ("Sewickley", (40.5343, -80.1859))
GEO_COLS = ["poi_density", "restaurants_open", "activity_dinner", "transit_daily_trips"]


def check_constant_columns(df):
    """A numeric column with <=1 distinct non-null value is either a genuine constant
    (an all-proxy source flag) or a broken join/enrichment. Flag it either way so it
    gets a human look rather than silently flatlining every heatmap."""
    problems = []
    for c in COLS:
        if c not in df.columns:
            continue
        nunique = df[c].dropna().nunique()
        if nunique <= 1:
            problems.append(f"CONSTANT: {c} has {nunique} distinct non-null value(s)")
    return problems


def check_percentile_floor(df):
    """Catches the exact defect class already found once: rank(pct=True, method='average')
    reports a zero-inflated floor (e.g. 97% of cells with no signal) as the *average* rank
    (~50) instead of the bottom. For every plotted column, find cells tied at that column's
    minimum; if a real share of the county sits there, their _pct must stay near the bottom."""
    problems = []
    for c in COLS:
        pct_col = f"{c}_pct"
        if c not in df.columns or pct_col not in df.columns:
            continue
        s = df[c].dropna()
        if s.empty:
            continue
        floor = s.min()
        floor_mask = df[c] == floor
        floor_share = floor_mask.mean()
        if floor_share > 0.10:
            floor_pct_max = df.loc[floor_mask, pct_col].max()
            if floor_pct_max > 20:
                problems.append(
                    f"FLOOR DRIFT: {c} -- {floor_share:.0%} of cells tied at the floor ({floor}) "
                    f"but {pct_col} reaches {floor_pct_max:.1f} among them (expected <= ~20)")
    return problems


def _neighborhood_pct(idx, lat, lng, pct_col):
    """Average the percentile over grid_disk(2) (~19 cells, ~700 m) around a point rather
    than reading one exact hex: several contract columns (poi_density in particular) are
    single-cell, unsmoothed OSM counts over a very zero-inflated county, so one hex can land
    on a parking lot or a corner store and swing wildly relative to its own neighborhood."""
    h = h3.latlng_to_cell(lat, lng, common.H3_RES)
    vals = [idx.loc[c, pct_col] for c in h3.grid_disk(h, 2) if c in idx.index]
    return (sum(vals) / len(vals)) if vals else None


def check_geography(df):
    """Downtown, Oakland, Shadyside, South Side and Strip District should rank high on
    density/activity; Sewickley -- a quiet outer borough -- should not. Flag any hot spot
    that scores below the 50th percentile, or a case where Sewickley outranks all of them."""
    problems = []
    idx = df.set_index("h3")
    for col in GEO_COLS:
        pct_col = f"{col}_pct"
        if pct_col not in df.columns:
            continue
        hot_vals = {}
        for name, (lat, lng) in HOT_SPOTS.items():
            v = _neighborhood_pct(idx, lat, lng, pct_col)
            if v is None:
                problems.append(f"GEOGRAPHY: {name} has no cell_features coverage nearby ({col})")
                continue
            hot_vals[name] = v
            if v < 50:
                problems.append(f"GEOGRAPHY: {name} averages only {v:.1f}th pct on {col} (expected dense, >=50)")
        cold_name, (clat, clng) = COLD_SPOT
        cold_v = _neighborhood_pct(idx, clat, clng, pct_col)
        if cold_v is None:
            problems.append(f"GEOGRAPHY: {cold_name} has no cell_features coverage nearby ({col})")
        elif hot_vals:
            worst_hot_name = min(hot_vals, key=hot_vals.get)
            if cold_v >= hot_vals[worst_hot_name]:
                problems.append(
                    f"GEOGRAPHY: {cold_name} averages {cold_v:.1f}th pct on {col}, at or above "
                    f"the lowest hot spot ({worst_hot_name}={hot_vals[worst_hot_name]:.1f})")
    return problems


def main():
    df = common.load("cell_features").merge(common.load_cells(), on="h3")
    out = common.ROOT / "data/sanity"
    out.mkdir(exist_ok=True)
    for c in COLS:
        fig, ax = plt.subplots(figsize=(8, 7))
        ax.scatter(df.lng, df.lat, c=df[f"{c}_pct"], s=3, cmap="viridis")
        ax.set_title(c)
        ax.set_aspect(1.3)
        fig.savefig(out / f"{c}.png", dpi=110)
        plt.close(fig)
    print(f"wrote {len(COLS)} heatmaps to {out}")

    problems = check_constant_columns(df) + check_percentile_floor(df) + check_geography(df)
    if problems:
        print(f"\n{len(problems)} sanity issue(s) found:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nno sanity issues found")


if __name__ == "__main__":
    main()
