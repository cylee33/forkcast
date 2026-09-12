"""Percentile helper shared by every sub-score.

Ranks are taken across the *scored set* (the h3 cells passed into `score_cells` for one
request), not across all 18,275 county cells. D/C/T/A/S_spend are concept-dependent
composites -- Demand, Competition etc. depend on the profile's weights, dayparts and
catchment -- so there is no single metro-wide reference distribution to rank a given
concept against without re-scoring all 18,275 cells for every request. Ranking within the
requested set keeps "80th percentile" meaningful relative to the cells actually being
compared for this search. Uses method="min" (as ingest/common.py's pct() does) so a block
of cells tied at the floor lands near 0, not at the block's midpoint.
"""
import pandas as pd


def pct(s: pd.Series) -> pd.Series:
    if len(s) <= 1:
        return pd.Series(100.0 if len(s) == 1 else [], index=s.index, dtype=float)
    return s.rank(pct=True, method="min") * 100.0
