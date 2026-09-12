"""Optional Yelp popularity signal for Pittsburgh candidate cells.

The model estimates historical ``log1p(review_count)`` associations. It does not
estimate revenue, survival, causal site impact, or the seven opportunity subscores.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

import joblib
import numpy as np
import pandas as pd

ARTIFACTS = Path(os.environ.get("FORKCAST_POPULARITY_ARTIFACTS", Path(__file__).with_name("artifacts")))
MODEL_PATH = ARTIFACTS / "yelp_popularity_hgb.joblib"
CELLS_PATH = ARTIFACTS / "pittsburgh_h3_demographics.parquet"
METADATA_PATH = ARTIFACTS / "yelp_popularity_metadata.json"


@lru_cache(maxsize=2)
def _load_bundle(path: Path = MODEL_PATH) -> dict:
    bundle = joblib.load(path)
    required = {"model", "scaler", "medians", "numeric_columns", "demographic_columns", "cuisines"}
    missing = required - set(bundle)
    if missing:
        raise ValueError(f"Popularity model artifact is missing fields: {sorted(missing)}")
    return bundle


@lru_cache(maxsize=2)
def _load_cells(path: Path = CELLS_PATH) -> pd.DataFrame:
    return pd.read_parquet(path)


def model_info(path: Path = METADATA_PATH) -> dict:
    """Return provenance, evaluation, and interpretation limits for UI/API metadata."""
    return json.loads(path.read_text())


def _feature_matrix(frame: pd.DataFrame, cuisines: Iterable[str], price_tier: int, bundle: dict):
    if price_tier not in {1, 2, 3, 4}:
        raise ValueError("price_tier must be 1, 2, 3, or 4")
    requested = tuple(dict.fromkeys(str(c).strip().lower() for c in cuisines if str(c).strip()))
    known = set(bundle["cuisines"])
    supported = tuple(c for c in requested if c in known and c != "unknown")
    unsupported = tuple(c for c in requested if c not in known)
    encoded = set(supported or ["unknown"])

    values = frame[bundle["numeric_columns"]].to_numpy(dtype=float).copy()
    values[:, 0] = float(price_tier)
    # The fitted experiment applies log1p to population density and income.
    for index in (1, 2):
        values[:, index] = np.log1p(np.maximum(values[:, index], 0))
    missing = ~np.isfinite(values)
    imputed = np.where(missing, bundle["medians"], values)
    numeric = bundle["scaler"].transform(imputed)
    cuisine = np.array([
        [float(name in encoded) for name in bundle["cuisines"]]
        for _ in range(len(frame))
    ])
    matrix = np.column_stack([numeric, missing.astype(float), cuisine])
    if not np.isfinite(matrix).all():
        raise ValueError("Popularity feature matrix contains non-finite values after imputation")
    return matrix, supported, unsupported


def score_popularity(
    cuisines: Iterable[str],
    price_tier: int,
    h3_ids: Iterable[str] | None = None,
    *,
    model_path: Path = MODEL_PATH,
    cells_path: Path = CELLS_PATH,
) -> pd.DataFrame:
    """Score Pittsburgh H3 cells and return an optional 0–100 relative signal.

    Percentiles always use the full Pittsburgh grid as their reference, so the
    same H3 retains its value when an analysis radius changes. Callers may pass
    the analysis radius as ``h3_ids`` to trim the returned rows. Coverage flags must remain attached.
    Metadata and caveats are available in ``result.attrs`` and :func:`model_info`.
    """
    bundle = _load_bundle(model_path)
    cells = _load_cells(cells_path)
    requested_h3 = list(dict.fromkeys(h3_ids)) if h3_ids is not None else None
    if requested_h3 is not None:
        available = cells.set_index("h3", drop=False)
        unknown_h3 = [cell for cell in requested_h3 if cell not in available.index]
        if unknown_h3:
            raise ValueError(f"No popularity demographics for {len(unknown_h3)} requested H3 cells")
    if requested_h3 is not None and not requested_h3:
        raise ValueError("At least one candidate H3 cell is required")

    # The percentile reference is always the full Pittsburgh county grid. A
    # candidate's score must not change when the user adjusts the map radius.
    matrix, supported, unsupported = _feature_matrix(cells, cuisines, price_tier, bundle)
    prediction = bundle["model"].predict(matrix)
    result = cells[["h3", "demographic_missing_count", "outside_training_range_count"]].copy()
    result["predicted_log_popularity"] = prediction
    result["popularity_pct"] = pd.Series(prediction).rank(method="average", pct=True).mul(100).to_numpy()
    if requested_h3 is not None:
        result = result.set_index("h3", drop=False).loc[requested_h3].reset_index(drop=True)
    result.attrs.update({
        "model": bundle["model_name"],
        "supported_cuisines": supported,
        "unsupported_cuisines": unsupported,
        "warning": bundle["warning"],
    })
    return result


def score_profile(profile: Mapping | object, h3_ids: Iterable[str] | None = None) -> pd.DataFrame:
    """Score an API ``ConceptProfile`` or equivalent mapping without importing ``api``."""
    if isinstance(profile, Mapping):
        cuisines, price_tier = profile["cuisines"], profile["price_tier"]
    else:
        cuisines, price_tier = profile.cuisines, profile.price_tier
    return score_popularity(cuisines, int(price_tier), h3_ids)
