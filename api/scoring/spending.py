"""Spending-fit helper, used both standalone (S_spend, §5.4) and as the SpendFit_j term
inside Demand's gravity sum (§5.2). "Peaks at match, not at richest": a cell's price mix
matching the concept's price_tier, and its income distribution matching income_fit, score
higher than simply the highest-income cell.
"""
import numpy as np
import pandas as pd

INCOME_FIT_CENTER = {"low": 10.0, "low_to_medium": 30.0, "medium": 50.0,
                     "medium_to_high": 70.0, "high": 90.0}
PRICE_COLS = {1: "local_price_1", 2: "local_price_2", 3: "local_price_3", 4: "local_price_4"}


def price_match(profile, f: pd.DataFrame) -> pd.Series:
    tier = profile.price_tier
    m = f[PRICE_COLS[tier]].fillna(0.0).copy()
    if tier - 1 in PRICE_COLS:
        m = m + 0.5 * f[PRICE_COLS[tier - 1]].fillna(0.0)
    if tier + 1 in PRICE_COLS:
        m = m + 0.5 * f[PRICE_COLS[tier + 1]].fillna(0.0)
    return m.clip(0.0, 1.0)


def spend_fit(profile, f: pd.DataFrame) -> pd.Series:
    """SpendFit_i in [0,1]. median_hh_income_pct is NULL on 288 cells (Census could not
    produce an estimate); rather than treat that as "average income" (a fabricated
    number), those rows fall back to price-match alone instead of propagating NaN."""
    pm = price_match(profile, f)
    center = INCOME_FIT_CENTER[profile.income_fit]
    inc_pct = f["median_hh_income_pct"]
    income_match = 1.0 - (inc_pct - center).abs() / 100.0
    return pd.Series(np.where(inc_pct.isna(), pm, (pm + income_match) / 2.0), index=f.index)


def raw_s_spend(profile, f: pd.DataFrame) -> pd.Series:
    capacity = f["spending_capacity"].fillna(0.0)
    return spend_fit(profile, f) * capacity
