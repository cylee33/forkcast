"""Rent estimate per cell: regression of hand-collected asking rents on ZORI (ZIP) + walkability. Always labeled estimate."""
import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from ingest import common

ZORI_URL = "https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv"
ZCTA_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"
FEATS = ["zori", "walkable_poi_density_pct"]
MIN_MANUAL_ROWS = 8
IMPUTED_CONFIDENCE_PENALTY = 0.2  # cells whose ZIP had no ZORI match are less trustworthy than the fit alone implies
IMPUTED_CONFIDENCE_FLOOR = 0.15


def zori_by_zip() -> pd.DataFrame:
    path = common.RAW / "zillow/zori_zip.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(ZORI_URL, timeout=120).content)
    df = pd.read_csv(path, dtype={"RegionName": str})
    df = df[(df.State == "PA")]
    last = [c for c in df.columns if c[:2] == "20"][-1]
    return df[["RegionName", last]].rename(columns={"RegionName": "zip", last: "zori"})


def zip_per_cell(cells: pd.DataFrame) -> pd.Series:
    path = common.RAW / "tiger/cb_2020_us_zcta520_500k.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(ZCTA_URL, timeout=600).content)
    z = gpd.read_file(f"zip://{path}")
    z = z[z.ZCTA5CE20.str.startswith("15")][["ZCTA5CE20", "geometry"]]
    pts = gpd.GeoDataFrame(cells[["h3"]], geometry=gpd.points_from_xy(cells.lng, cells.lat), crs="EPSG:4326")
    j = gpd.sjoin(pts, z, how="left", predicate="within")
    return j.drop_duplicates("h3").set_index("h3")["ZCTA5CE20"]


def fit(manual: pd.DataFrame, feats: pd.DataFrame) -> tuple[np.ndarray, float]:
    X = np.column_stack([np.ones(len(feats)), feats[FEATS].values.astype(float)])
    y = manual.rent_psf_yr.values.astype(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss_res, ss_tot = ((y - pred) ** 2).sum(), ((y - y.mean()) ** 2).sum()
    return coef, 1 - ss_res / ss_tot if ss_tot else 0.0


def predict(coef: np.ndarray, feats: pd.DataFrame) -> pd.Series:
    X = np.column_stack([np.ones(len(feats)), feats[FEATS].values.astype(float)])
    return pd.Series(X @ coef, index=feats.index)


def confidence_and_source(r2: float, imputed: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Per-cell rent_confidence/rent_source: cells whose ZIP had no real ZORI match (silently
    imputed to the county median) are marked less confident and distinguishable from real matches,
    so the Cost sub-score doesn't weigh an imputed cell the same as one backed by a real ZIP."""
    matched_conf = float(np.clip(0.3 + 0.5 * r2, 0.3, 0.8))
    imputed_conf = float(np.clip(matched_conf - IMPUTED_CONFIDENCE_PENALTY, IMPUTED_CONFIDENCE_FLOOR, matched_conf))
    confidence = imputed.map({True: imputed_conf, False: matched_conf}).astype(float)
    source = imputed.map({True: "zori_imputed+manual_regression", False: "zori+manual_regression"})
    return confidence, source


def main():
    args = common.cli(__doc__)
    manual_path = common.ROOT / "data/rents_manual.csv"
    manual_raw = pd.read_csv(manual_path)
    if len(manual_raw) < MIN_MANUAL_ROWS:
        raise SystemExit(
            f"{manual_path} need at least {MIN_MANUAL_ROWS} rows to fit the rent regression, "
            f"found {len(manual_raw)}. Hand-collect asking rents into this file (see brain/tasks.md) "
            "before running this step."
        )
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    osm = common.load("osm_cells").set_index("h3").reindex(cells.h3)
    feats = pd.DataFrame({"h3": cells.h3.values})
    feats["zip"] = zip_per_cell(cells).reindex(cells.h3).values
    feats = feats.merge(zori_by_zip(), on="zip", how="left")
    feats["zori_imputed"] = feats.zori.isna()
    feats["zori"] = feats.zori.fillna(feats.zori.median())
    feats["walkable_poi_density_pct"] = common.pct(osm.walkable_poi_density.fillna(0)).values
    manual = common.points_to_h3(manual_raw)
    mf = manual.merge(feats, on="h3", how="inner")
    assert len(mf) >= MIN_MANUAL_ROWS, (
        f"only {len(mf)} of {len(manual)} hand-collected rows fell inside the cell grid after "
        f"the h3 join (dropped {len(manual) - len(mf)}); need at least {MIN_MANUAL_ROWS} to fit."
    )
    coef, r2 = fit(mf, mf)
    out = pd.DataFrame({"h3": feats.h3, "est_rent_psf_yr": predict(coef, feats).clip(8, 80).values})
    out["rent_confidence"], out["rent_source"] = confidence_and_source(r2, feats.zori_imputed)
    out["rent_resolution"] = "zip"
    common.save(out, "rent")
    n_imputed = int(feats.zori_imputed.sum())
    print(f"rent: n_manual={len(mf)} r2={r2:.2f} n_zori_imputed={n_imputed}/{len(feats)} "
          f"median est ${out.est_rent_psf_yr.median():.0f}/sqft/yr")


if __name__ == "__main__":
    main()
