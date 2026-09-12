import h3
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


def test_confidence_and_source_penalizes_imputed_zori():
    r = load_script("10_rent_proxy")
    imputed = pd.Series([False, True, False, True])
    conf, source = r.confidence_and_source(r2=0.9, imputed=imputed)
    matched_conf, imputed_conf = conf[~imputed], conf[imputed]
    # matched cells all get the same R2-driven ceiling; imputed cells all get a strictly lower value
    assert (matched_conf == matched_conf.iloc[0]).all()
    assert (imputed_conf == imputed_conf.iloc[0]).all()
    assert imputed_conf.iloc[0] < matched_conf.iloc[0]
    assert set(source[~imputed]) == {"zori+manual_regression"}
    assert set(source[imputed]) == {"zori_imputed+manual_regression"}


def test_confidence_and_source_respects_floor_and_ceiling():
    r = load_script("10_rent_proxy")
    imputed = pd.Series([True, False])
    conf_low_r2, _ = r.confidence_and_source(r2=0.0, imputed=imputed)
    conf_high_r2, _ = r.confidence_and_source(r2=1.0, imputed=imputed)
    assert conf_low_r2[~imputed].iloc[0] == pytest.approx(0.3)
    assert conf_high_r2[~imputed].iloc[0] == pytest.approx(0.8)
    assert (conf_low_r2 >= r.IMPUTED_CONFIDENCE_FLOOR).all()
    assert (conf_high_r2 <= 0.8).all()


def test_merge_guard_fails_loudly_when_hand_collected_rows_fall_outside_grid(monkeypatch, tmp_path):
    """8 manual rows pass the raw row-count gate, but only 3 of their h3 cells are in the (synthetic,
    tiny) grid -- the merge silently drops the rest unless the post-merge assertion catches it."""
    r = load_script("10_rent_proxy")
    grid_cells = list(h3.grid_disk(h3.latlng_to_cell(40.44, -79.99, 9), 1))
    cells = pd.DataFrame({"h3": grid_cells,
                          "lat": [h3.cell_to_latlng(c)[0] for c in grid_cells],
                          "lng": [h3.cell_to_latlng(c)[1] for c in grid_cells]})
    osm_cells = pd.DataFrame({"h3": grid_cells, "walkable_poi_density": [1.0] * len(grid_cells)})

    monkeypatch.setattr(r.common, "ROOT", tmp_path)
    monkeypatch.setattr(r.common, "load_cells", lambda: cells)
    monkeypatch.setattr(r.common, "load", lambda name: osm_cells)
    monkeypatch.setattr(r, "zip_per_cell", lambda cells: pd.Series(["15213"] * len(cells), index=cells.h3))
    monkeypatch.setattr(r, "zori_by_zip", lambda: pd.DataFrame({"zip": ["15213"], "zori": [1500.0]}))

    in_lat, in_lng = h3.cell_to_latlng(grid_cells[0])
    rows = pd.DataFrame({
        "address": [f"addr{i}" for i in range(8)],
        "lat": [in_lat] * 3 + [0.0] * 5,   # last 5 land on Null Island, far outside the grid
        "lng": [in_lng] * 3 + [0.0] * 5,
        "rent_psf_yr": [20.0 + i for i in range(8)],
        "sqft": [1000] * 8,
        "source_url": [""] * 8,
        "collected_on": ["2026-01-01"] * 8,
    })
    (tmp_path / "data").mkdir()
    rows.to_csv(tmp_path / "data" / "rents_manual.csv", index=False)

    monkeypatch.setattr("sys.argv", ["10_rent_proxy.py"])
    with pytest.raises(AssertionError, match=r"only 3 of 8"):
        r.main()
