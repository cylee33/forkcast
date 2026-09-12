"""Fixtures for the backend and web tracks: ~200 real cells around Oakland + a fake-scored RecommendResponse."""
import json

import h3
import numpy as np

from ingest import common

CENTER = (40.4406, -79.9600)  # Oakland
DEMO_PROFILE = {
    "concept_name": "Korean street food", "cuisines": ["korean"], "subcuisine": ["street_food"],
    "substitute_cuisines": ["japanese", "chinese"], "complementary_cuisines": ["bubble_tea"],
    "service_format": "fast_casual", "price_tier": 1, "avg_ticket_usd": 13,
    "dayparts": {"lunch": 0.3, "dinner": 0.4, "late_night": 0.3}, "customer_archetypes": ["students", "young_adults"],
    "target_age_mix": {"18_24": 0.5, "25_34": 0.3}, "dine_in_importance": 0.4, "takeout_importance": 0.8,
    "delivery_importance": 0.7, "parking_importance": 0.1, "pedestrian_importance": 0.9, "transit_importance": 0.6,
    "nightlife_importance": 0.6, "office_importance": 0.2, "university_importance": 0.9, "family_importance": 0.1,
    "visibility_importance": 0.6, "income_fit": "low_to_medium", "catchment": "walk", "catchment_tau_min": 8,
    "footprint_sqft": [800, 1500], "seats": 24, "supplier_types": ["asian_grocer", "wholesale"],
    "direct_competitor_description": "casual Korean restaurants, Korean fried chicken, bibimbap, tteokbokki",
    "is_franchise": False, "proposed_weights": {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
    "confidence": 0.9, "clarifying_questions": []}
KEYS = ["D", "C", "T", "A", "S_spend", "K", "Sup"]


def main():
    rng = np.random.default_rng(7)
    center = h3.latlng_to_cell(*CENTER, 9)
    disk = set(h3.grid_disk(center, 8))
    cf = common.load("cell_features")
    sample = cf[cf.h3.isin(disk)].head(250)
    sample.to_parquet(common.FIXTURES / "cell_features_sample.parquet", index=False)

    feats, zone_id = [], {}
    scores = {h: rng.uniform(20, 95, size=7) for h in sample.h3}
    ranked = sorted(sample.h3, key=lambda h: -float(np.dot(list(DEMO_PROFILE["proposed_weights"].values()), scores[h])))
    for i, h in enumerate(ranked[:5]):
        for c in h3.grid_disk(h, 1):
            zone_id.setdefault(c, i + 1)
    for h in sample.h3:
        s = dict(zip(KEYS, map(float, scores[h])))
        total = float(np.dot(list(DEMO_PROFILE["proposed_weights"].values()), list(s.values())))
        feats.append({"type": "Feature", "geometry": common.cell_polygon(h).__geo_interface__,
                      "properties": {"h3": h, "total": total, **s, "confidence": 0.6, "zone_id": zone_id.get(h)}})
    zones = []
    for i, h in enumerate(ranked[:5]):
        s = dict(zip(KEYS, map(float, scores[h])))
        zones.append({"zone_id": i + 1, "name": f"Zone {i + 1} (fixture)", "total": float(np.dot(list(DEMO_PROFILE["proposed_weights"].values()), list(s.values()))),
                      "best_h3": h, "subscores": s, "confidence": 0.6,
                      "drivers": ["Student demand 91st pct", "Late-night traffic 84th pct", "No direct Korean competitors"],
                      "risks": ["Rent estimate low confidence", "Parking 12th pct"],
                      "gap": {"demand": 82, "supply": 20, "gap": 62}, "gap_flag": True,
                      "competitors_direct": [], "competitors_indirect": [{"id": "google:x", "name": "Sushi Fuku", "distance_m": 210, "similarity": 0.62, "rating": 4.4, "reviews": 800}],
                      "anchors": [{"name": "University of Pittsburgh", "type": "university", "distance_m": 300}],
                      # Rent is unmeasured for every real cell right now (Task 13's data run is still
                      # pending hand-collected rents). Representing it as a plausible number here would
                      # teach the backend/web tracks to expect a rent that does not exist yet -- so this
                      # fixture uses the contract's "absent" value (null / 0 confidence), matching the
                      # real feature store, instead of the brief's literal 28.0 / 0.5.
                      "est_rent_psf_yr": None, "rent_confidence": 0.0})
    resp = {"analysis_id": "fixture-0001", "profile": DEMO_PROFILE,
            "weights": DEMO_PROFILE["proposed_weights"],
            "cells": {"type": "FeatureCollection", "features": feats}, "zones": zones, "backtest_rho": None}
    (common.FIXTURES / "recommend_sample.json").write_text(json.dumps(resp))
    print(f"fixtures: {len(sample)} cells, {len(zones)} zones")


if __name__ == "__main__":
    main()
