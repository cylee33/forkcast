import json

import pandas as pd

from ingest import common


def test_cell_features_sample_exists_and_has_pct_columns():
    df = pd.read_parquet(common.FIXTURES / "cell_features_sample.parquet")
    assert 150 <= len(df) <= 400
    assert "pop_total_pct" in df.columns and "cuisine_affinity" in df.columns


def test_recommend_sample_validates():
    from api.models import RecommendResponse
    data = json.loads((common.FIXTURES / "recommend_sample.json").read_text())
    r = RecommendResponse.model_validate(data)
    assert len(r.zones) >= 3 and r.cells["type"] == "FeatureCollection"
