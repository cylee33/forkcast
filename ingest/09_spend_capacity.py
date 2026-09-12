"""Spending capacity (CEX food-away-from-home × ACS income mix) and local price-tier profile."""
import pathlib

import pandas as pd
import yaml

from ingest import common

CEX = yaml.safe_load((pathlib.Path(__file__).with_name("cex_food_away.yaml")).read_text())


def capacity(row: pd.Series) -> float:
    return float(row["hh_count"] * sum(row[k] * v for k, v in CEX.items()))


def price_profile(places: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    p = places[places.is_open & places.price_level.notna()]
    counts = p.groupby(["h3", "price_level"]).size().unstack(fill_value=0).reindex(columns=[1, 2, 3, 4], fill_value=0)
    out = pd.DataFrame({"h3": cells.h3}).set_index("h3")
    for lvl in [1, 2, 3, 4]:
        s = counts[lvl].reindex(out.index, fill_value=0.0) if lvl in counts else pd.Series(0.0, index=out.index)
        out[f"local_price_{lvl}"] = common.disk_sum(s, 2)
    tot = out.sum(axis=1).mask(lambda s: s == 0)
    for lvl in [1, 2, 3, 4]:
        out[f"local_price_{lvl}"] = (out[f"local_price_{lvl}"] / tot).fillna(0.0)
    return out.reset_index()


def main():
    args = common.cli(__doc__)
    acs = common.load("acs")
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    spend = acs.set_index("h3").reindex(cells.h3).fillna(0)
    out = pd.DataFrame({"h3": cells.h3, "spending_capacity": [capacity(r) for _, r in spend.iterrows()]})
    out = out.merge(price_profile(common.load("places"), cells), on="h3")
    common.save(out, "spend")
    n_priced = int((out[["local_price_1", "local_price_2", "local_price_3", "local_price_4"]].sum(axis=1) > 0).sum())
    print(f"spend: {len(out)} cells, capacity total ${out.spending_capacity.sum()/1e9:.2f}B, "
          f"{n_priced}/{len(out)} cells with a real local price profile")


if __name__ == "__main__":
    main()
