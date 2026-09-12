"""Tests for api/services/*. No network calls: an autouse fixture makes any attempt to
construct a live Gemini client fail the test loudly, and the concept-parser golden cases
replay checked-in cache fixtures under data/raw/llm/ instead."""
import pandas as pd
import pytest

from api.models import SUBSCORE_KEYS, ConceptProfile
from api.services import explainer, reverse
from api.services.concept_parser import parse
from api.services.llm_schema import LLMWeights
from api.services.refine import refine


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("test suite attempted a live Gemini client call")

    monkeypatch.setattr("google.genai.Client", _boom)


# --------------------------------------------------------------------------------------
# concept_parser: three golden demo concepts, replayed from cached LLM responses
# --------------------------------------------------------------------------------------

GOLDEN_CONCEPTS = [
    ("Cheap Korean street food under $15 for college students, open late.",
     {"price_tier_max": 2, "cuisine_substr": "korean"}),
    ("Premium Korean BBQ, $50 per person, groups and parking.",
     {"price_tier_min": 3, "cuisine_substr": "korean"}),
    ("Family steak & seafood, big dining room, parking, weekend dinners.",
     {"price_tier_min": 3, "cuisine_substr": "steak"}),
]


@pytest.mark.parametrize("text,expect", GOLDEN_CONCEPTS)
def test_concept_parser_golden_cached(text, expect):
    profile = parse(text)
    assert isinstance(profile, ConceptProfile)
    cuisines_low = " ".join(profile.cuisines).lower()
    assert expect["cuisine_substr"] in cuisines_low
    if "price_tier_max" in expect:
        assert profile.price_tier <= expect["price_tier_max"]
    if "price_tier_min" in expect:
        assert profile.price_tier >= expect["price_tier_min"]
    # A cached golden response is a genuine LLM parse, not the low-confidence keyword fallback.
    assert profile.confidence >= 0.5


def test_concept_parser_golden_concepts_are_distinct():
    profiles = [parse(text) for text, _ in GOLDEN_CONCEPTS]
    signatures = {(p.service_format, p.price_tier) for p in profiles}
    assert len(signatures) > 1


# --------------------------------------------------------------------------------------
# concept_parser: deterministic keyword fallback when the LLM is unavailable
# --------------------------------------------------------------------------------------

def test_parser_falls_back_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr("api.services.concept_parser.llm_client.generate_structured",
                         lambda *a, **kw: None)
    profile = parse("A cozy neighborhood Italian trattoria with pasta and wine.")
    assert isinstance(profile, ConceptProfile)
    assert profile.cuisines == ["italian"]
    assert profile.confidence < 0.5
    assert any("LLM was unavailable" in q for q in profile.clarifying_questions)
    # Numbers come only from the taxonomy defaults / fixed tables, never invented.
    assert profile.avg_ticket_usd == 35.0  # italian's default_price_tier is 3
    assert profile.dayparts == {"dinner": 0.8, "weekend": 0.2}


def test_parser_fallback_never_calls_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    profile = parse("Some completely unmatched gibberish description zzzqxq.")
    assert isinstance(profile, ConceptProfile)
    assert profile.confidence < 0.5


# --------------------------------------------------------------------------------------
# refine: LLM patch -> correct field diff; degrades to unchanged profile + empty diff
# --------------------------------------------------------------------------------------

def _base_profile() -> ConceptProfile:
    return ConceptProfile(
        concept_name="Korean street food", cuisines=["korean"], service_format="fast_casual",
        price_tier=1, avg_ticket_usd=13.0, dayparts={"lunch": 0.3, "dinner": 0.4, "late_night": 0.3},
        customer_archetypes=["students"], income_fit="low_to_medium", catchment="walk",
        catchment_tau_min=8, footprint_sqft=(800, 1500), seats=24, supplier_types=["asian_grocer"],
        direct_competitor_description="casual Korean spots", is_franchise=False,
        proposed_weights={"D": 0.25, "C": 0.18, "T": 0.22, "A": 0.15, "S_spend": 0.08, "K": 0.09, "Sup": 0.03},
        confidence=0.9,
    )


def test_refine_produces_correct_diff(monkeypatch):
    profile = _base_profile()

    def fake_generate_structured(purpose, cache_input, prompt, schema):
        from api.services.llm_schema import from_concept_profile
        patched = from_concept_profile(profile).model_copy(deep=True)
        patched.price_tier = 3
        patched.avg_ticket_usd = 50.0
        patched.service_format = "casual_dining"
        patched.proposed_weights = LLMWeights(**{"D": 0.25, "C": 0.18, "T": 0.12, "A": 0.12,
                                                  "S_spend": 0.15, "K": 0.12, "Sup": 0.06})
        return patched

    monkeypatch.setattr("api.services.refine.llm_client.generate_structured", fake_generate_structured)
    patched, diff = refine(profile, "make it premium, $50 ticket")

    assert patched.price_tier == 3
    assert patched.avg_ticket_usd == 50.0
    assert patched.service_format == "casual_dining"
    assert diff["price_tier"] == {"from": 1, "to": 3}
    assert diff["avg_ticket_usd"] == {"from": 13.0, "to": 50.0}
    assert diff["service_format"] == {"from": "fast_casual", "to": "casual_dining"}
    # Untouched fields must not appear in the diff.
    assert "concept_name" not in diff
    assert "cuisines" not in diff


def test_refine_degrades_to_unchanged_profile_when_llm_unavailable(monkeypatch):
    profile = _base_profile()
    monkeypatch.setattr("api.services.refine.llm_client.generate_structured", lambda *a, **kw: None)
    patched, diff = refine(profile, "make it premium")
    assert patched is profile
    assert diff == {}


# --------------------------------------------------------------------------------------
# explainer: only computed numbers may appear; an invented number forces the fallback
# --------------------------------------------------------------------------------------

def _zone_fixture() -> dict:
    return {
        "zone_id": 1, "best_h3": "892a8471423ffff", "total": 80.7, "confidence": 0.6,
        "subscores": {"D": 74.07, "C": 94.76, "T": 90.44, "A": 83.23, "S_spend": 78.28,
                       "K": 49.63, "Sup": 68.09},
        "gap": {"demand": 82, "supply": 20, "gap": 62},
        "gap_flag": True,
        "competitors_direct": [],
        "competitors_indirect": [{"id": "google:x", "name": "Sushi Fuku", "distance_m": 210,
                                   "similarity": 0.62, "rating": 4.4, "reviews": 800}],
        "anchors": [{"name": "University of Pittsburgh", "type": "university", "distance_m": 300}],
        "est_rent_psf_yr": None,
        "rent_confidence": 0.0,
    }


def test_explainer_rejects_invented_number():
    zone = _zone_fixture()
    assert explainer.has_invented_numbers("The score is 74 with confidence 60%.", zone) is False
    assert explainer.has_invented_numbers("Expect $413,287 in annual profit.", zone) is True


def test_explain_falls_back_when_llm_invents_a_number(monkeypatch):
    profile = _base_profile()
    zone = _zone_fixture()
    monkeypatch.setattr("api.services.explainer.llm_client.generate_text",
                         lambda *a, **kw: "This cell will do $413,287 in annual profit.")
    text = explain_and_check(profile, zone)
    assert "413,287" not in text
    assert "unknown" in text.lower()  # rent is None -> must say unknown, never guess


def explain_and_check(profile, zone):
    return explainer.explain(profile, zone)


def test_explain_fallback_never_mentions_rent_number_when_null():
    profile = _base_profile()
    zone = _zone_fixture()
    text = explainer._fallback_template(profile, zone)
    assert "unknown" in text.lower()
    assert zone["est_rent_psf_yr"] is None


# --------------------------------------------------------------------------------------
# reverse: top_n ranked archetypes from the (injected, fake) scoring engine
# --------------------------------------------------------------------------------------

def _fake_scoring(h3_pool):
    def fake_load_features():
        return pd.DataFrame({"h3": h3_pool})

    def fake_score_cells(profile, h3s, weights):
        rng_seed = abs(hash(profile.concept_name)) % (2**32)
        import numpy as np
        rng = np.random.default_rng(rng_seed)
        df = pd.DataFrame({"h3": h3s})
        for k in SUBSCORE_KEYS:
            df[k] = rng.uniform(0, 100, len(h3s))
        df["total"] = sum(df[k] * weights.get(k, 0) for k in SUBSCORE_KEYS)
        df["gap_flag"] = False
        return df

    def fake_validate(proposed, available):
        return proposed

    return fake_load_features, fake_score_cells, fake_validate


def test_reverse_returns_top_n_ranked_archetypes(monkeypatch):
    h3_pool = [f"89fake{i:04d}ffff" for i in range(30)]
    load_features, score_cells, validate = _fake_scoring(h3_pool)

    import h3 as h3mod
    monkeypatch.setattr(h3mod, "latlng_to_cell", lambda lat, lng, res: "center")
    monkeypatch.setattr(h3mod, "grid_disk", lambda c, k: h3_pool)
    monkeypatch.setattr(h3mod, "cell_to_latlng", lambda c: (40.44, -79.95))

    out = reverse.reverse(40.44, -79.95, top_n=5, score_cells=score_cells,
                           load_features=load_features, weights_validate=validate)

    assert len(out) == 5
    totals = [r["total"] for r in out]
    assert totals == sorted(totals, reverse=True)
    for r in out:
        assert set(r) == {"archetype", "concept_name", "total", "subscores", "why"}
        assert set(r["subscores"]) <= set(SUBSCORE_KEYS)
        assert isinstance(r["why"], str) and r["why"]


def test_reverse_returns_empty_list_when_no_cells_in_radius(monkeypatch):
    load_features, score_cells, validate = _fake_scoring([])

    import h3 as h3mod
    monkeypatch.setattr(h3mod, "latlng_to_cell", lambda lat, lng, res: "center")
    monkeypatch.setattr(h3mod, "grid_disk", lambda c, k: [])

    out = reverse.reverse(40.44, -79.95, score_cells=score_cells, load_features=load_features,
                           weights_validate=validate)
    assert out == []
