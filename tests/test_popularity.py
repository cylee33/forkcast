import numpy as np
import pytest

from ml.popularity import MODEL_PATH, model_info, score_popularity, score_profile

requires_local_artifact = pytest.mark.skipif(
    not MODEL_PATH.exists(),
    reason="Yelp-derived runtime artifacts are deliberately not stored in the public repository",
)


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
