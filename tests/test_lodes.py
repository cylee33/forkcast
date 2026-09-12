import pandas as pd

from tests.conftest import load_script


def test_to_block_groups_rolls_up_blocks():
    lodes = load_script("02_lodes")
    raw = pd.DataFrame({"w_geocode": ["420030001001001", "420030001001002", "420030002001001"],
                        "C000": [10, 5, 7], "CE03": [4, 1, 2]})
    out = lodes.to_block_groups(raw).set_index("GEOID")
    assert out.loc["420030001001", "workers_daytime"] == 15
    assert out.loc["420030001001", "workers_high_wage"] == 5
    assert len(out) == 2
