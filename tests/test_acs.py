import json

import pandas as pd
import pytest

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


def test_chunks_splits_long_var_list_under_census_cap():
    acs = load_script("01_census_acs")
    long_vars = [f"B00001_{i:03d}E" for i in range(75)]
    chunks = acs._chunks(long_vars)
    assert len(chunks) > 1
    assert all(len(c) <= 50 for c in chunks)
    assert [v for c in chunks for v in c] == long_vars  # nothing dropped or reordered


def test_fetch_masks_jam_sentinel_to_nan_not_zero(monkeypatch, tmp_path):
    """Census's -666666666 ("estimate not available") must become NaN, not be clipped to a
    plausible $0 by clip(lower=0) -- the headline defect this fix removes."""
    acs = load_script("01_census_acs")
    monkeypatch.setattr(acs.common, "RAW", tmp_path)
    header = acs.VARS + acs.GEO_COLS
    row = ["-666666666" if v == "B19013_001E" else "5" for v in acs.VARS] + ["42", "003", "010100", "1"]
    path = tmp_path / "acs" / "bg_2023.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([header, row]))
    df = acs.fetch()
    assert pd.isna(df["B19013_001E"].iloc[0])
    assert df["B01003_001E"].iloc[0] == 5  # a real value elsewhere in the same row is untouched


def test_merge_chunks_combines_variables_one_row_per_block_group():
    acs = load_script("01_census_acs")
    geo = ["state", "county", "tract", "block group"]
    chunk1 = [["B01_001E", *geo],
              ["10", "42", "003", "100", "1"],
              ["20", "42", "003", "100", "2"]]
    chunk2 = [["B02_001E", *geo],
              ["30", "42", "003", "100", "1"],
              ["40", "42", "003", "100", "2"]]
    merged_rows = acs._merge_chunks([chunk1, chunk2])
    df = pd.DataFrame(merged_rows[1:], columns=merged_rows[0])
    assert len(df) == 2  # one row per block group, not duplicated by the merge
    assert list(df.columns).count("state") == 1  # geo columns not duplicated/suffixed
    assert {"B01_001E", "B02_001E"}.issubset(df.columns)
    row1 = df[df["block group"] == "1"].iloc[0]
    assert row1["B01_001E"] == "10" and row1["B02_001E"] == "30"


def test_merge_chunks_asserts_on_row_count_drop():
    """A structurally valid but short chunk (missing a block group) must fail loudly, not
    silently drop rows into a cached, trusted file via the inner join."""
    acs = load_script("01_census_acs")
    geo = ["state", "county", "tract", "block group"]
    chunk1 = [["B01_001E", *geo],
              ["10", "42", "003", "100", "1"],
              ["20", "42", "003", "100", "2"]]
    chunk2 = [["B02_001E", *geo],
              ["30", "42", "003", "100", "1"]]  # missing block group "2"
    with pytest.raises(AssertionError, match="dropped rows"):
        acs._merge_chunks([chunk1, chunk2])
