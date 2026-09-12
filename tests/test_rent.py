import numpy as np
import pandas as pd
import pytest

from tests.conftest import load_script


def test_fit_recovers_linear_relationship():
    r = load_script("10_rent_proxy")
    feats = pd.DataFrame({"zori": [1000, 1500, 2000, 2500], "walkable_poi_density_pct": [10, 40, 60, 90]})
    manual = pd.DataFrame({"rent_psf_yr": 5 + 0.01 * feats.zori + 0.1 * feats.walkable_poi_density_pct})
    coef, r2 = r.fit(manual, feats)
    assert r2 > 0.99
    pred = r.predict(coef, feats)
    assert np.allclose(pred, manual.rent_psf_yr, atol=1e-6)


def test_main_fails_clearly_on_too_few_manual_rows(monkeypatch, tmp_path):
    r = load_script("10_rent_proxy")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "rents_manual.csv").write_text(
        "address,lat,lng,rent_psf_yr,sqft,source_url,collected_on\n"
    )
    monkeypatch.setattr(r.common, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["10_rent_proxy.py"])
    with pytest.raises(SystemExit, match=r"need at least 8 rows.*found 0"):
        r.main()
