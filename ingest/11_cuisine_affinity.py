"""Observed cuisine affinity (proposal §3.4): engagement of same/complementary cuisines nearby + price compatibility.
No demographic or ancestry inputs."""
import numpy as np
import pandas as pd

from ingest import common, taxonomy


def affinity(places: pd.DataFrame, cells: pd.DataFrame, price_profile: pd.DataFrame) -> pd.DataFrame:
    tax = taxonomy.load()["cuisines"]
    p = places[places.is_open & places.cuisine_key.notna()].copy()
    p["eng"] = np.log1p(p.reviews.fillna(0)) * p.rating.fillna(3.5)
    eng = p.groupby(["h3", "cuisine_key"])["eng"].sum().unstack(fill_value=0.0)
    idx = pd.Index(cells.h3)
    disk = {}
    for c in eng.columns:
        disk[c] = common.disk_sum(eng[c].reindex(idx, fill_value=0.0), 2)
    pp = price_profile.set_index("h3").reindex(idx).fillna(0.0)
    result = {c: pd.Series(0.0, index=idx) for c in tax}
    for c, spec in tax.items():
        own = disk.get(c, pd.Series(0.0, index=idx))
        comp = sum((disk.get(k, pd.Series(0.0, index=idx)) for k in spec.get("complementary", [])), pd.Series(0.0, index=idx))
        tier = spec.get("default_price_tier", 2)
        price_ok = pp[f"local_price_{tier}"] + 0.5 * (pp.get(f"local_price_{max(tier - 1, 1)}", 0) + pp.get(f"local_price_{min(tier + 1, 4)}", 0))
        raw = own + 0.5 * comp + price_ok * (own.mean() if own.mean() > 0 else 1.0)
        result[c] = common.pct(raw)
    out = pd.DataFrame({"h3": idx})
    out["cuisine_affinity"] = [{c: float(result[c][h]) for c in tax} for h in idx]
    return out


def main():
    args = common.cli(__doc__)
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    out = affinity(common.load("places"), cells, common.load("spend"))
    common.save(out, "affinity")
    print(f"affinity: {len(out)} cells × {len(out.cuisine_affinity.iloc[0])} cuisines")


if __name__ == "__main__":
    main()
