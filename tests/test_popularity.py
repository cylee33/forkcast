import json
from pathlib import Path

import numpy as np
import pytest
import ml.popularity as popularity

from ml.popularity import (
    enrich_cell_collection,
    model_info,
    popularity_available,
    score_popularity,
    score_profile,
)

requires_local_artifact = pytest.mark.skipif(
    not popularity_available(),
    reason="Yelp-derived runtime artifacts are deliberately not stored in the public repository",
)


def test_cell_enrichment_is_optional_when_local_artifacts_are_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(popularity, "MODEL_PATH", tmp_path / "missing-model.joblib")
    monkeypatch.setattr(popularity, "CELLS_PATH", tmp_path / "missing-cells.parquet")
    monkeypatch.setattr(popularity, "METADATA_PATH", tmp_path / "missing-metadata.json")
    cells = {"type": "FeatureCollection", "features": []}

    enriched = enrich_cell_collection(cells, {"cuisines": ["korean"], "price_tier": 2})
    assert enriched == cells
    assert enriched is not cells
    with pytest.raises(FileNotFoundError, match="runtime artifacts"):
        enrich_cell_collection(cells, {"cuisines": ["korean"], "price_tier": 2}, required=True)


@requires_local_artifact
def test_popularity_artifact_scores_all_pittsburgh_cells_deterministically():
    first = score_popularity(["korean"], 2)
    second = score_popularity(["korean"], 2)
    assert len(first) == 18_275
    assert first.h3.is_unique
    assert first.popularity_pct.between(0, 100).all()
    assert np.allclose(first.predicted_log_popularity, second.predicted_log_popularity)
    assert first.attrs["model"] == "hgb_demographics"
    assert "Pittsburgh" in first.attrs["warning"]


@requires_local_artifact
def test_profile_subset_preserves_order_and_changes_with_concept():
    full = score_popularity(["korean"], 2)
    candidate_h3 = full.h3.iloc[[10, 3, 20]].tolist()
    korean = score_profile({"cuisines": ["korean"], "price_tier": 2}, candidate_h3)
    pizza = score_profile({"cuisines": ["pizza"], "price_tier": 1}, candidate_h3)
    assert korean.h3.tolist() == candidate_h3
    expected = full.set_index("h3").loc[candidate_h3].popularity_pct.to_numpy()
    assert np.allclose(korean.popularity_pct, expected)
    assert not np.allclose(korean.predicted_log_popularity, pizza.predicted_log_popularity)


@requires_local_artifact
def test_unknown_cuisine_and_bad_inputs_are_explicit():
    unknown = score_popularity(["not_in_training"], 2, [score_popularity(["korean"], 2).h3.iloc[0]])
    assert unknown.attrs["supported_cuisines"] == ()
    assert unknown.attrs["unsupported_cuisines"] == ("not_in_training",)
    with pytest.raises(ValueError, match="price_tier"):
        score_popularity(["korean"], 5)
    with pytest.raises(ValueError, match="No popularity demographics"):
        score_popularity(["korean"], 2, ["not-an-h3"])


@requires_local_artifact
def test_metadata_forbids_success_and_pittsburgh_accuracy_claims():
    metadata = model_info()
    assert metadata["pittsburgh_status"].startswith("inference only")
    assert "Do not replace" in metadata["integration"]


@requires_local_artifact
def test_fixture_cells_can_be_enriched_without_changing_existing_scores():
    fixture = json.loads(Path("data/fixtures/recommend_sample.json").read_text())
    original = fixture["cells"]
    enriched = enrich_cell_collection(original, fixture["profile"], required=True)

    assert popularity_available()
    assert enriched is not original
    assert "historical_popularity_pct" not in original["features"][0]["properties"]
    assert len(enriched["features"]) == len(original["features"])
    for before, after in zip(original["features"], enriched["features"], strict=True):
        assert after["properties"]["h3"] == before["properties"]["h3"]
        assert after["properties"]["total"] == before["properties"]["total"]
        assert 0 <= after["properties"]["historical_popularity_pct"] <= 100
        assert isinstance(
            after["properties"]["historical_popularity_demographic_missing_count"], int
        )
        assert isinstance(
            after["properties"]["historical_popularity_outside_training_range_count"], int
        )
