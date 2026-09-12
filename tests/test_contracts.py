import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_concept_profile_schema_loads():
    s = json.loads((ROOT / "contracts/concept_profile.json").read_text())
    assert s["title"] == "ConceptProfile"
    assert "proposed_weights" in s["properties"]


def test_pydantic_mirror_matches_schema_required_fields():
    from api.models import ConceptProfile
    s = json.loads((ROOT / "contracts/concept_profile.json").read_text())
    assert set(s["required"]) <= set(ConceptProfile.model_fields)


def test_pydantic_rejects_bad_price_tier():
    from api.models import ConceptProfile
    with pytest.raises(Exception):
        ConceptProfile(concept_name="x", cuisines=["korean"], service_format="cafe", price_tier=9,
                       avg_ticket_usd=10, dayparts={"lunch": 1}, customer_archetypes=["students"],
                       income_fit="low", catchment="walk", catchment_tau_min=8, footprint_sqft=(800, 1500),
                       seats=20, supplier_types=["asian_grocer"], direct_competitor_description="korean",
                       is_franchise=False, proposed_weights={}, confidence=0.9)


def test_subscore_keys():
    from api.models import SUBSCORE_KEYS
    assert SUBSCORE_KEYS == ["D", "C", "T", "A", "S_spend", "K", "Sup"]
