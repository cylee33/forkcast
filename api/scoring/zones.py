"""Zones (§5.7): merge adjacent top-decile cells into connected components (h3 grid_disk
adjacency), rank by each component's best cell, return the top `top_n`.

This returns partial zone records (zone_id, member cells, best_h3, total, subscores,
confidence) -- `api/scoring/engine.py` enriches these into the full contract `Zone` shape
(name, drivers, risks, gap, competitors, anchors, rent) since that needs the places/OSM
tables this function isn't given.
"""
import h3
import pandas as pd

from api.models import SUBSCORE_KEYS


def build_zones(scored: pd.DataFrame, features: pd.DataFrame, top_n: int = 8) -> list[dict]:
    if scored.empty:
        return []

    threshold = scored["total"].quantile(0.9)
    pool = scored[scored["total"] >= threshold]
    if pool.empty:
        pool = scored.nlargest(min(len(scored), top_n), "total")

    cellset = set(pool.index)
    visited: set[str] = set()
    components: list[list[str]] = []
    for c in pool.index:
        if c in visited:
            continue
        stack = [c]
        visited.add(c)
        comp = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for n in h3.grid_disk(cur, 1):
                if n in cellset and n not in visited:
                    visited.add(n)
                    stack.append(n)
        components.append(comp)

    components.sort(key=lambda comp: -pool.loc[comp, "total"].max())

    out = []
    for i, comp in enumerate(components[:top_n]):
        best_h3 = pool.loc[comp, "total"].idxmax()
        row = pool.loc[best_h3]
        out.append({
            "zone_id": i + 1,
            "h3_cells": comp,
            "best_h3": best_h3,
            "total": float(row["total"]),
            "subscores": {k: (None if pd.isna(row[k]) else float(row[k])) for k in SUBSCORE_KEYS},
            "confidence": float(pool.loc[comp, "confidence"].mean()),
        })
    return out
