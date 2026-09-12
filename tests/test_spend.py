import pandas as pd

from tests.conftest import load_script


def test_capacity_weights_brackets_by_households():
    s = load_script("09_spend_capacity")
    row = pd.Series({"hh_count": 100, "income_lt25k": 0.5, "income_25_50k": 0.5, "income_50_75k": 0,
                     "income_75_100k": 0, "income_100_150k": 0, "income_150k_plus": 0})
    assert s.capacity(row) == 100 * (0.5 * 1500 + 0.5 * 2300)


def test_price_profile_shares_sum_to_one():
    import h3
    s = load_script("09_spend_capacity")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    places = pd.DataFrame({"h3": [c, c, c], "price_level": [1, 2, 2], "is_open": [True] * 3})
    out = s.price_profile(places, pd.DataFrame({"h3": [c]})).set_index("h3").loc[c]
    assert abs(out[["local_price_1", "local_price_2", "local_price_3", "local_price_4"]].sum() - 1) < 1e-9
    assert abs(out["local_price_2"] - 2 / 3) < 1e-9
