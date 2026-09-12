"""Confidence (§5.6): mean of five per-cell signals -- how many of the 7 sub-scores are
actually computable this row (K is real-but-absent right now, so this currently caps near
6/7), a freshness placeholder (cell_features carries no per-row freshness column today, so
this is a documented neutral 1.0 rather than fabricated variation), rent_confidence (a
genuine per-row column, reading 0.0 when there is no rent estimate), whether traffic_source
is "real" or "proxy" (it is "proxy" everywhere right now, Task 10), and nearby place density
capped at 1.0 past 10 open restaurants.
"""
import numpy as np
import pandas as pd

from api.models import SUBSCORE_KEYS

FRESHNESS = 1.0


def compute(f: pd.DataFrame, subscores: pd.DataFrame) -> pd.Series:
    completeness = subscores[SUBSCORE_KEYS].notna().sum(axis=1) / len(SUBSCORE_KEYS)
    rent_conf = f["rent_confidence"].fillna(0.0)
    traffic_term = np.where(f["traffic_source"] == "real", 1.0, 0.5)
    places_term = (f["restaurants_open"].fillna(0.0) / 10.0).clip(upper=1.0)
    total = (completeness.to_numpy() + FRESHNESS + rent_conf.to_numpy() + traffic_term
             + places_term.to_numpy()) / 5.0
    return pd.Series(total, index=f.index)
