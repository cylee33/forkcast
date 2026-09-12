import numpy as np
import pandas as pd

from tests.conftest import load_script


def test_embed_text_composes_name_categories_summary():
    e = load_script("08_place_embeddings")
    row = pd.Series({"name": "Seoul Bulgogi", "categories": ["korean_restaurant", "restaurant"], "summary": "Casual Korean."})
    assert e.embed_text(row) == "Seoul Bulgogi. korean restaurant, restaurant. Casual Korean."


def test_l2_normalize_gives_unit_length():
    e = load_script("08_place_embeddings")
    out = e.l2_normalize([3.0, 4.0])
    assert np.isclose(np.linalg.norm(out), 1.0)
    assert np.allclose(out, [0.6, 0.8])
