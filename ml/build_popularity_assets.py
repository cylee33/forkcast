"""Build portable runtime assets from the completed isolated Yelp experiment."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"


def build(experiment: Path, geo_cells: Path) -> None:
    sys.path.insert(0, str(experiment))
    legacy = joblib.load(experiment / "artifacts/model.joblib")
    pipeline = legacy["pipeline"]
    features = pipeline["features"]
    portable = {
        "model": pipeline["model"],
        "scaler": features.scaler_,
        "medians": features.medians_,
        "numeric_columns": features.columns_,
        "demographic_columns": legacy["demographic_columns"],
        "cuisines": legacy["cuisines"],
        "model_name": legacy["selected_model"],
        "target": legacy["target"],
        "training_demographic_ranges": legacy["training_demographic_ranges"],
        "warning": legacy["warning"],
    }

    tracts = gpd.read_parquet(experiment / "artifacts/demographic_tracts.parquet")
    tracts = tracts.loc[tracts.region.eq("Pittsburgh")].copy()
    cells = pd.read_parquet(geo_cells, columns=["h3", "lat", "lng"])
    points = gpd.GeoDataFrame(
        cells,
        geometry=gpd.points_from_xy(cells.lng, cells.lat),
        crs=4326,
    )
    columns = ["tract_geoid", *portable["demographic_columns"], "geometry"]
    joined = points.sjoin(tracts[columns], how="left", predicate="intersects")
    duplicates = int(joined.h3.duplicated().sum())
    joined = joined.sort_values(["h3", "tract_geoid"]).drop_duplicates("h3")
    if joined.tract_geoid.isna().any():
        raise ValueError(f"{joined.tract_geoid.isna().sum()} H3 centers do not match an ACS tract")
    joined["price_tier"] = np.nan
    joined["demographic_missing_count"] = joined[portable["demographic_columns"]].isna().sum(axis=1)
    ranges = portable["training_demographic_ranges"]
    outside = pd.DataFrame({
        column: joined[column].lt(ranges[column][0]) | joined[column].gt(ranges[column][1])
        for column in portable["demographic_columns"]
    })
    joined["outside_training_range_count"] = outside.sum(axis=1)

    ARTIFACTS.mkdir(exist_ok=True)
    model_path = ARTIFACTS / "yelp_popularity_hgb.joblib"
    cells_path = ARTIFACTS / "pittsburgh_h3_demographics.parquet"
    joblib.dump(portable, model_path)
    runtime_columns = ["h3", "tract_geoid", "price_tier", *portable["demographic_columns"],
                       "demographic_missing_count", "outside_training_range_count"]
    joined[runtime_columns].to_parquet(cells_path, index=False)

    summary = json.loads((experiment / "artifacts/summary.json").read_text())
    diagnostics = json.loads((experiment / "artifacts/diagnostics.json").read_text())
    test_metrics = json.loads((experiment / "artifacts/test_metrics.json").read_text())
    demographics_metadata = json.loads(
        (experiment / "artifacts/demographics_metadata.json").read_text()
    )
    metadata = {
        "schema_version": 1,
        "model": portable["model_name"],
        "target": portable["target"],
        "role": "optional historical online-popularity signal",
        "training_regions": ["Philadelphia County", "Hillsborough County / Tampa"],
        "validation_region": "Marion County / Indianapolis",
        "test_region": "Davidson County / Nashville",
        "pittsburgh_status": "inference only; no Yelp labels in this release",
        "test_metrics": next(row for row in test_metrics if row["model"] == portable["model_name"]),
        "demographic_ablation": diagnostics["bootstrap"],
        "training_rows": sum(row["n"] for row in summary["counts"] if row["split"] == "train"),
        "validation_rows": sum(row["n"] for row in summary["counts"] if row["split"] == "validation"),
        "test_rows": sum(row["n"] for row in summary["counts"] if row["split"] == "test"),
        "h3_rows": len(joined),
        "h3_boundary_duplicates_resolved": duplicates,
        "acs_vintage": "2017–2021 ACS 5-year; 2021 cartographic tract boundaries",
        "demographic_definitions": demographics_metadata["definitions"],
        "source_files": demographics_metadata["sources"],
        "source_caveats": demographics_metadata["caveats"],
        "runtime_versions": {
            package: importlib.metadata.version(package)
            for package in ["scikit-learn", "joblib", "numpy", "pandas", "pyarrow"]
        },
        "artifact_sha256": {
            model_path.name: hashlib.sha256(model_path.read_bytes()).hexdigest(),
            cells_path.name: hashlib.sha256(cells_path.read_bytes()).hexdigest(),
        },
        "warning": portable["warning"],
        "integration": "Do not replace D/C/T/A/S_spend/K/Sup or claim Pittsburgh accuracy.",
    }
    (ARTIFACTS / "yelp_popularity_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps({"h3_rows": len(joined), "duplicates": duplicates,
                      "missing_demographics": int(joined.demographic_missing_count.gt(0).sum()),
                      "outside_training_range": int(joined.outside_training_range_count.gt(0).sum())}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--geo-cells", type=Path, default=Path("data/processed/geo_cells.parquet"))
    args = parser.parse_args()
    build(args.experiment.resolve(), args.geo_cells.resolve())
