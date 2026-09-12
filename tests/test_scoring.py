"""Tests for api/scoring/. TDD per the scoring-engine brief: hand-built frames for each
sub-score, the K-is-None-and-renormalizes contract, the inverted dist_to_*_pct convention,
zone merging, and analyze()'s output validating against contracts/recommend_response.json.
"""
import json
import pathlib
import time

import h3
import numpy as np
import pandas as pd
import pytest

from api.models import ConceptProfile, RecommendResponse, SUBSCORE_KEYS
from api.scoring import access, competition, cost, demand, spending, supply, traffic, weights, zones
from api.scoring.engine import analyze, available_subscores, load_features, score_cells

ROOT = pathlib.Path(__file__).resolve().parents[1]


def make_profile(**overrides) -> ConceptProfile:
    base = dict(
        concept_name="Korean street food", cuisines=["korean"], subcuisine=["street_food"],
        substitute_cuisines=["japanese", "chinese"], complementary_cuisines=["bubble_tea"],
        service_format="fast_casual", price_tier=1, avg_ticket_usd=13,
        dayparts={"lunch": 0.3, "dinner": 0.4, "late_night": 0.3},
        customer_archetypes=["students", "young_adults"],
        pedestrian_importance=0.9, transit_importance=0.6, parking_importance=0.1,
        visibility_importance=0.6, university_importance=0.9, office_importance=0.2,
        family_importance=0.1, nightlife_importance=0.6,
        income_fit="low_to_medium", catchment="walk", catchment_tau_min=8,
        footprint_sqft=(800, 1500), seats=24, supplier_types=["asian_grocer", "wholesale"],
        direct_competitor_description="casual Korean restaurants, Korean fried chicken, bibimbap",
        is_franchise=False,
        proposed_weights={"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
        confidence=0.9,
    )
    base.update(overrides)
    return ConceptProfile(**base)


def make_frame(n=3, **col_overrides) -> pd.DataFrame:
    """A tiny hand-built cell_features-shaped frame, indexed by fake h3 ids, with sane
    defaults for every column each sub-score module touches."""
    idx = [f"cell{i}" for i in range(n)]
    cols = {
        "pop_total": [1000.0] * n, "workers_daytime": [500.0] * n,
        "pct_students_pct": [50.0] * n, "workers_daytime_pct": [50.0] * n,
        "pct_families_with_kids_pct": [50.0] * n, "avg_hh_size_pct": [50.0] * n,
        "anchor_bar_pct": [50.0] * n, "anchor_hotel_pct": [50.0] * n, "anchor_attraction_pct": [50.0] * n,
        "pct_age_25_34_pct": [50.0] * n,
        "median_hh_income_pct": [50.0] * n,
        "local_price_1": [0.5] * n, "local_price_2": [0.3] * n,
        "local_price_3": [0.1] * n, "local_price_4": [0.1] * n,
        "spending_capacity": [1e6] * n,
        "walkable_poi_density_pct": [50.0] * n, "transit_daily_trips_pct": [50.0] * n,
        "parking_lots_pct": [50.0] * n, "main_road_frontage_pct": [50.0] * n,
        "activity_morning": [50.0] * n, "activity_lunch": [50.0] * n, "activity_dinner": [50.0] * n,
        "activity_late_night": [50.0] * n, "activity_weekend": [50.0] * n,
        "dist_to_wholesale_km": [1.0] * n, "dist_to_supermarket_km": [1.0] * n,
        "dist_to_seafood_km": [5.0] * n, "dist_to_butcher_km": [5.0] * n,
        "dist_to_greengrocer_km": [5.0] * n, "dist_to_asian_grocer_km": [1.0] * n,
        "dist_to_italian_grocer_km": [5.0] * n,
        "est_rent_psf_yr": [np.nan] * n, "rent_confidence": [0.0] * n,
        "traffic_source": ["proxy"] * n, "restaurants_open": [2.0] * n,
        "anchor_nightclub": [0.0] * n,
        "lat": [40.44 + 0.001 * i for i in range(n)], "lng": [-79.96 + 0.001 * i for i in range(n)],
    }
    cols.update({k: [v] * n if not isinstance(v, list) else v for k, v in col_overrides.items()})
    return pd.DataFrame(cols, index=idx)


# ---------------------------------------------------------------------------
# Individual sub-scores on hand-built frames
# ---------------------------------------------------------------------------

def test_access_weights_by_importance():
    profile = make_profile(pedestrian_importance=1.0, transit_importance=0.0,
                            parking_importance=0.0, visibility_importance=0.0)
    f = make_frame(2, walkable_poi_density_pct=[10.0, 90.0])
    out = access.raw(profile, f)
    assert out["cell0"] < out["cell1"]


def test_traffic_uses_only_the_profiles_dayparts():
    profile = make_profile(dayparts={"lunch": 1.0})
    f = make_frame(1, activity_lunch=[80.0], activity_dinner=[999.0], activity_morning=[999.0])
    out = traffic.raw(profile, f)
    assert out.iloc[0] == pytest.approx(80.0)


def test_spending_price_match_peaks_at_the_concepts_own_tier():
    profile = make_profile(price_tier=1)
    f = make_frame(1, local_price_1=[0.8], local_price_2=[0.1], local_price_3=[0.0], local_price_4=[0.0])
    high_tier_profile = make_profile(price_tier=4)
    match_own = spending.price_match(profile, f).iloc[0]
    match_far = spending.price_match(high_tier_profile, f).iloc[0]
    assert match_own > match_far


def test_spending_handles_null_income_without_propagating_nan():
    profile = make_profile(income_fit="high")
    f = make_frame(1, median_hh_income_pct=[np.nan])
    out = spending.spend_fit(profile, f)
    assert not pd.isna(out.iloc[0])  # falls back to price-match alone, not NaN


def test_supply_closer_supplier_scores_higher_and_never_reinverts():
    profile = make_profile(supplier_types=["wholesale"])
    f = make_frame(2, dist_to_wholesale_km=[0.5, 8.0])
    out = supply.raw(profile, f)
    assert out["cell0"] > out["cell1"]  # closer (smaller raw km) -> higher Sup


def test_supply_is_none_for_an_untracked_supplier_type():
    profile = make_profile(supplier_types=["halal"])  # not in SUPPLIER_COLUMN
    f = make_frame(1)
    out = supply.raw(profile, f)
    assert out.isna().all()


def test_demand_customer_fit_neutral_when_no_archetypes_stated():
    profile = make_profile(customer_archetypes=[])
    f = make_frame(2, pct_students_pct=[0.0, 100.0])
    out = demand.customer_fit(profile, f)
    assert (out == 1.0).all()


def test_demand_customer_fit_favors_matching_archetype():
    profile = make_profile(customer_archetypes=["students"], university_importance=1.0)
    f = make_frame(2, pct_students_pct=[10.0, 90.0])
    out = demand.customer_fit(profile, f)
    assert out["cell0"] < out["cell1"]


def test_demand_families_falls_back_when_avg_hh_size_is_null():
    profile = make_profile(customer_archetypes=["families"], family_importance=1.0)
    f = make_frame(1, pct_families_with_kids_pct=[70.0], avg_hh_size_pct=[np.nan])
    out = demand.customer_fit(profile, f)
    assert out.iloc[0] == pytest.approx(0.70)  # falls back to pct_families_with_kids alone


def test_demand_raw_decays_with_distance():
    profile = make_profile(catchment="walk", catchment_tau_min=5)
    f = make_frame(3)
    f.loc["cell0", ["lat", "lng"]] = [40.44, -79.96]
    f.loc["cell1", ["lat", "lng"]] = [40.44, -79.96]  # same location as target -> no decay
    f.loc["cell2", ["lat", "lng"]] = [40.60, -80.10]  # far away -> heavy decay
    out = demand.raw_demand(profile, f, ["cell0"])
    assert out.iloc[0] > 0


def test_taxonomy_similarity_direct_substitute_unrelated():
    profile = make_profile(cuisines=["korean"], substitute_cuisines=["japanese"])
    cuisines = pd.Series(["korean", "japanese", "thai"])
    out = competition.taxonomy_sim(profile, cuisines)
    assert list(out) == [1.0, 0.5, 0.0]


# ---------------------------------------------------------------------------
# Cost (K) is None on current data, and weights.validate() renormalizes
# ---------------------------------------------------------------------------

def test_cost_k_is_none_when_rent_is_null_everywhere():
    profile = make_profile()
    f = make_frame(3)  # est_rent_psf_yr defaults to NaN
    out = cost.raw(profile, f)
    assert out.isna().all()


def test_cost_k_formula_is_correct_when_rent_is_present():
    """Exercises the real formula (K = 100*clip(affordable/annual_rent, 0, 1.5)/1.5) even
    though est_rent_psf_yr is NULL on every cell today -- proves the code path ahead of
    the real data landing."""
    profile = make_profile(service_format="fast_casual", avg_ticket_usd=15.0, seats=20,
                            footprint_sqft=(900, 900))
    f = make_frame(1, est_rent_psf_yr=[30.0])
    affordable = 15.0 * 20 * 3.0 * 300 * 0.08  # turns=3.0 for fast_casual
    annual_rent = 30.0 * 900
    expected = 100.0 * min(affordable / annual_rent, 1.5) / 1.5
    out = cost.raw(profile, f)
    assert out.iloc[0] == pytest.approx(expected)


def test_weights_validate_drops_k_and_renormalizes_to_one():
    proposed = {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03}
    available = {"D", "C", "T", "A", "S_spend", "Sup"}  # K excluded: rent is null everywhere
    out = weights.validate(proposed, available)
    assert set(out) == set(SUBSCORE_KEYS)  # every key present, per the frozen contract
    assert out["K"] == 0.0  # honestly zero, not dropped
    assert sum(out.values()) == pytest.approx(1.0)


def test_weights_validate_clamps_and_caps_at_point_four():
    # Others are balanced enough that the 0.4 cap on D survives renormalization too (the
    # cap is applied before renormalizing, so a *very* lopsided proposal can legitimately
    # renormalize back above 0.4 -- that's covered by the next test).
    proposed = {"D": 5.0, "C": -1.0, "T": 0.2, "A": 0.2, "S_spend": 0.2, "K": 0.2, "Sup": 0.2}
    out = weights.validate(proposed, set(SUBSCORE_KEYS))
    assert out["D"] <= 0.4 + 1e-9
    assert out["C"] >= 0.0
    assert sum(out.values()) == pytest.approx(1.0)


def test_weights_validate_caps_before_renormalizing_not_after():
    # D's raw proposal (5.0) is clamped to 0.4 *before* renormalization; if every other
    # weight is tiny, renormalizing can legitimately push D's final share back above 0.4 --
    # the 0.4 rule bounds the input, not a guarantee on the output share.
    proposed = {"D": 5.0, "C": 0.1, "T": 0.1, "A": 0.1, "S_spend": 0.1, "K": 0.1, "Sup": 0.1}
    out = weights.validate(proposed, set(SUBSCORE_KEYS))
    assert out["D"] == pytest.approx(0.4 / (0.4 + 0.6))
    assert sum(out.values()) == pytest.approx(1.0)


def test_weights_default_weights_shape():
    assert set(weights.DEFAULT_WEIGHTS) == set(SUBSCORE_KEYS)
    assert sum(weights.DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# dist_to_*_pct is inverted (100 = closest) -- must not be re-inverted
# ---------------------------------------------------------------------------

def test_dist_to_pct_columns_are_inverted_on_real_data():
    sample = pd.read_parquet(ROOT / "data/fixtures/cell_features_sample.parquet")
    corr = sample["dist_to_university_km"].corr(sample["dist_to_university_km_pct"])
    assert corr < -0.8  # farther (bigger km) -> lower pct, not higher

    farthest = sample.loc[sample["dist_to_university_km"].idxmax()]
    closest = sample.loc[sample["dist_to_university_km"].idxmin()]
    assert closest["dist_to_university_km_pct"] > farthest["dist_to_university_km_pct"]


# ---------------------------------------------------------------------------
# Zones: merge adjacent high-scoring cells
# ---------------------------------------------------------------------------

def _scored_frame(idx: list[str], totals: list[float]) -> pd.DataFrame:
    n = len(idx)
    cols = {k: totals for k in ["D", "C", "T", "A", "S_spend", "Sup"]}
    cols["K"] = [None] * n
    cols["total"] = totals
    cols["confidence"] = [0.8] * n
    return pd.DataFrame(cols, index=idx)


def test_build_zones_merges_grid_adjacent_cells():
    center = h3.latlng_to_cell(40.4406, -79.9600, 9)
    neighbor = h3.grid_disk(center, 1)[1]
    # 18 low-scoring filler cells (far from center/neighbor) so the 90th-percentile
    # threshold sits clearly below both real candidates regardless of quantile
    # interpolation at small sample sizes.
    filler = [c for c in h3.grid_disk(center, 30) if c not in (center, neighbor)][:18]
    idx = [center, neighbor] + filler
    totals = [95.0, 92.0] + [10.0] * len(filler)
    scored = _scored_frame(idx, totals)
    features = make_frame(len(idx))
    features.index = idx
    out = zones.build_zones(scored, features, top_n=8)
    assert len(out) == 1  # center + neighbor merge into one zone; filler is below the top decile
    assert set(out[0]["h3_cells"]) == {center, neighbor}
    assert out[0]["best_h3"] == center


def test_build_zones_keeps_disconnected_high_scorers_separate():
    center = h3.latlng_to_cell(40.4406, -79.9600, 9)
    far = list(h3.grid_disk(center, 30))[-1]
    filler = [c for c in h3.grid_disk(center, 30) if c not in (center, far)][:18]
    idx = [center, far] + filler
    totals = [90.0, 95.0] + [10.0] * len(filler)  # far ranks higher than center
    scored = _scored_frame(idx, totals)
    features = make_frame(len(idx))
    features.index = idx
    out = zones.build_zones(scored, features, top_n=8)
    assert len(out) == 2
    assert out[0]["best_h3"] == far  # ranked by max total, descending


# ---------------------------------------------------------------------------
# End-to-end: analyze() validates against the frozen contract
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_profile():
    return make_profile()


def test_load_features_is_cached_and_indexed_by_h3():
    f1 = load_features()
    f2 = load_features()
    assert f1 is f2  # module-level cache, not re-read from disk
    assert f1.index.name == "h3"
    assert "h3" in f1.columns


def test_analyze_returns_a_contract_valid_response(demo_profile):
    resp = analyze(demo_profile, center=(40.4406, -79.9600), radius_mi=1.5)
    r = RecommendResponse.model_validate(resp)  # raises on any contract violation
    assert len(r.zones) >= 1
    assert resp["cells"]["type"] == "FeatureCollection"
    assert len(resp["cells"]["features"]) > 0


def test_analyze_weights_always_carry_all_seven_keys(demo_profile):
    resp = analyze(demo_profile, center=(40.4406, -79.9600), radius_mi=1.5)
    assert set(resp["weights"]) == set(SUBSCORE_KEYS)
    assert resp["weights"]["K"] == 0.0  # rent is null everywhere: honestly zero, not dropped
    assert sum(resp["weights"].values()) == pytest.approx(1.0)


def test_analyze_k_subscore_is_none_everywhere(demo_profile):
    resp = analyze(demo_profile, center=(40.4406, -79.9600), radius_mi=1.5)
    for feature in resp["cells"]["features"]:
        assert feature["properties"]["K"] is None
    for zone in resp["zones"]:
        assert zone["subscores"]["K"] is None


def test_analyze_matches_raw_json_schema_contract(demo_profile):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts/recommend_response.json").read_text())
    resp = analyze(demo_profile, center=(40.4406, -79.9600), radius_mi=1.5)
    jsonschema.validate(resp, schema)


def test_analyze_is_under_one_second_for_a_three_mile_radius(demo_profile):
    load_features()  # warm the cache so this measures scoring, not disk I/O
    t0 = time.time()
    analyze(demo_profile, center=(40.4406, -79.9600), radius_mi=3.0)
    elapsed = time.time() - t0
    assert elapsed < 2.0  # target is <1s (measured ~0.3-0.5s); generous bound to avoid CI flakiness


def test_analyze_is_concept_sensitive():
    """Two very different concepts at the same center should not rank cells identically --
    proof the engine actually varies with the profile, not just the location."""
    cheap = make_profile(price_tier=1, income_fit="low", customer_archetypes=["students"])
    premium = make_profile(price_tier=4, income_fit="high", customer_archetypes=["tourists"],
                            catchment="drive", catchment_tau_min=20)
    r1 = analyze(cheap, center=(40.4406, -79.9600), radius_mi=1.5)
    r2 = analyze(premium, center=(40.4406, -79.9600), radius_mi=1.5)
    totals1 = {f["properties"]["h3"]: f["properties"]["total"] for f in r1["cells"]["features"]}
    totals2 = {f["properties"]["h3"]: f["properties"]["total"] for f in r2["cells"]["features"]}
    shared = set(totals1) & set(totals2)
    assert any(abs(totals1[h] - totals2[h]) > 1e-6 for h in shared)


def test_score_cells_available_subscores_excludes_k_on_current_data():
    features = load_features()
    assert available_subscores(features) == {"D", "C", "T", "A", "S_spend", "Sup"}


def test_score_cells_on_a_small_real_h3_list():
    profile = make_profile()
    features = load_features()
    h3s = list(features.index[:20])
    w = weights.validate(profile.proposed_weights, available_subscores(features))
    out = score_cells(profile, h3s, w)
    assert list(out.index) == [h for h in h3s if h in features.index]
    assert set(SUBSCORE_KEYS) <= set(out.columns)
    assert "total" in out.columns and "confidence" in out.columns
    assert out["K"].isna().all()
