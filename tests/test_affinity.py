import h3
import pandas as pd

from tests.conftest import load_script


def test_affinity_higher_near_engaged_same_cuisine():
    a = load_script("11_cuisine_affinity")
    c1 = h3.latlng_to_cell(40.44, -79.99, 9)
    c2 = h3.latlng_to_cell(40.55, -80.10, 9)  # far away
    places = pd.DataFrame({"h3": [c1], "cuisine_key": ["korean"], "reviews": [500], "rating": [4.6],
                           "price_level": [2], "is_open": [True]})
    cells = pd.DataFrame({"h3": [c1, c2]})
    pp = pd.DataFrame({"h3": [c1, c2], "local_price_1": [0, 0], "local_price_2": [1, 1],
                       "local_price_3": [0, 0], "local_price_4": [0, 0]})
    out = a.affinity(places, cells, pp).set_index("h3")
    assert out.loc[c1, "cuisine_affinity"]["korean"] > out.loc[c2, "cuisine_affinity"]["korean"]
