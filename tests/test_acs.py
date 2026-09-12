import pandas as pd

from tests.conftest import load_script


def test_derive_computes_shares():
    acs = load_script("01_census_acs")
    raw = pd.DataFrame([{
        "GEOID": "420030001001", "B01003_001E": 1000, "B11001_001E": 400, "B19013_001E": 50000,
        **{v: 0 for v in acs.VARS if v not in ("B01003_001E", "B11001_001E", "B19013_001E")},
    }])
    raw["B19001_001E"] = 400
    raw["B19001_002E"] = 100  # <10k → lt25k bucket
    raw["B25003_001E"] = 400
    raw["B25003_003E"] = 300
    raw["B01001_001E"] = 1000
    raw["B01001_007E"] = 100  # male 18-19
    out = acs.derive(raw).iloc[0]
    assert out["pop_total"] == 1000
    assert abs(out["income_lt25k"] - 0.25) < 1e-9
    assert abs(out["pct_renters"] - 0.75) < 1e-9
    assert abs(out["pct_age_18_24"] - 0.10) < 1e-9
