"""Suppliers sub-score Sup (§5.4): Sup = 100*exp(-dist_to_needed_supplier_km / 8), using
the nearest of whichever `dist_to_*_km` columns match `profile.supplier_types`.

This uses the raw `_km` column directly, NOT the `_pct` companion -- `dist_to_*_pct` is
inverted (100 = closest per contracts/cell_features.md) specifically so that "higher pct
= better" holds when a percentile column is used directly as a sub-score; since Sup builds
its own 0-100 scale from the raw km via exp decay, there is nothing to invert here, and nothing
here re-inverts it.
"""
import numpy as np
import pandas as pd

SUPPLIER_COLUMN = {
    "wholesale": "dist_to_wholesale_km", "supermarket": "dist_to_supermarket_km",
    "seafood": "dist_to_seafood_km", "butcher": "dist_to_butcher_km",
    "greengrocer": "dist_to_greengrocer_km", "asian_grocer": "dist_to_asian_grocer_km",
    "italian_grocer": "dist_to_italian_grocer_km",
}
DECAY_KM = 8.0


def raw(profile, f: pd.DataFrame) -> pd.Series:
    cols = [SUPPLIER_COLUMN[t] for t in profile.supplier_types if t in SUPPLIER_COLUMN]
    if not cols:
        # the concept names a supplier type we don't track distance for (e.g. halal,
        # kosher) -- this is a genuine data gap, not "no supplier nearby", so return
        # None/NaN rather than a fabricated 0.
        return pd.Series(np.nan, index=f.index)
    dist = f[cols].min(axis=1)
    return 100.0 * np.exp(-dist / DECAY_KM)
