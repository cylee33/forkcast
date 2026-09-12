"""Cost sub-score K (§5.4): K = 100 * clip(affordable_rent / annual_rent, 0, 1.5) / 1.5,
where affordable_rent = avg_ticket_usd * seats * turns_per_day(service_format) * 300 days *
8%, and annual_rent = est_rent_psf_yr * midpoint(footprint_sqft).

est_rent_psf_yr is NULL on every one of the 18,275 current cells (decision D19: the
hand-collected rents this regression needs haven't been gathered yet). This returns an
all-NaN Series -- never a fabricated number -- so the response's K reads as None and
weights.validate() drops its weight and renormalizes the rest. The formula is exercised by
a synthetic-rent unit test in tests/test_scoring.py so the code path is proven correct
ahead of the real data landing.
"""
import numpy as np
import pandas as pd

TURNS_PER_DAY = {
    "quick_service": 4.0, "fast_casual": 3.0, "casual_dining": 1.5, "fine_dining": 1.0,
    "bar": 2.0, "cafe": 3.0, "ghost_kitchen": 6.0,
}
OPERATING_DAYS = 300
SALES_TO_RENT_PCT = 0.08


def raw(profile, f: pd.DataFrame) -> pd.Series:
    rent = f["est_rent_psf_yr"]
    if not rent.notna().any():
        return pd.Series(np.nan, index=f.index)
    turns = TURNS_PER_DAY.get(profile.service_format, 2.0)
    affordable = profile.avg_ticket_usd * profile.seats * turns * OPERATING_DAYS * SALES_TO_RENT_PCT
    sqft = sum(profile.footprint_sqft) / 2.0
    annual_rent = rent * sqft
    return (100.0 * (affordable / annual_rent).clip(0.0, 1.5) / 1.5)
