"""text -> ConceptProfile. Structured Gemini output first (cached, one retry on a
Pydantic validation failure); falls back to a deterministic keyword parser over
ingest/cuisine_taxonomy.yaml when the LLM is unavailable or never validates."""
import pathlib

import yaml

from api.models import ConceptProfile
from api.services import llm_client
from api.services.llm_schema import LLMConceptProfile, to_concept_profile

TAXONOMY_PATH = pathlib.Path(__file__).resolve().parents[2] / "ingest/cuisine_taxonomy.yaml"

WEIGHTS_BY_FORMAT = {
    "quick_service": {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
    "fast_casual": {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
    "casual_dining": {"D": .25, "C": .18, "T": .12, "A": .12, "S_spend": .15, "K": .12, "Sup": .06},
    "fine_dining": {"D": .18, "C": .15, "T": .08, "A": .10, "S_spend": .25, "K": .15, "Sup": .09},
    "cafe": {"D": .25, "C": .15, "T": .25, "A": .17, "S_spend": .08, "K": .07, "Sup": .03},
    "bar": {"D": .25, "C": .15, "T": .25, "A": .17, "S_spend": .08, "K": .07, "Sup": .03},
    "ghost_kitchen": {"D": .40, "C": .15, "T": .05, "A": .00, "S_spend": .05, "K": .25, "Sup": .10},
}
AVG_TICKET_BY_TIER = {1: 12.0, 2: 20.0, 3: 35.0, 4: 65.0}
TAU_MIN_BY_CATCHMENT = {"walk": 8.0, "transit": 15.0, "drive": 25.0}

PROMPT_TEMPLATE = """You are Forkcast's restaurant-concept analyst. Read the concept description
below and return a ConceptProfile JSON that captures its cuisine, service format, price tier,
target customers, and location-fit importances. Set proposed_weights over exactly the keys
D, C, T, A, S_spend, K, Sup (they need not sum to 1 -- the backend renormalizes). Set confidence
in [0,1] reflecting how unambiguous the description is, and list clarifying_questions for
anything left underspecified.

Concept description:
{text}
"""


def _load_taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY_PATH.read_text())["cuisines"]


def _match_cuisine(low_text: str, taxonomy: dict) -> tuple[str, dict]:
    for key, entry in taxonomy.items():
        if any(alias in low_text for alias in entry["aliases"]):
            return key, entry
    return "american", taxonomy["american"]


def _match_service_format(low_text: str) -> str:
    if "fine dining" in low_text or "upscale" in low_text or "premium" in low_text:
        return "fine_dining"
    if "ghost kitchen" in low_text or "delivery only" in low_text or "delivery-only" in low_text:
        return "ghost_kitchen"
    if "quick service" in low_text or "counter service" in low_text or "fast food" in low_text:
        return "quick_service"
    if "cafe" in low_text or "coffee" in low_text or "espresso" in low_text:
        return "cafe"
    if "bar" in low_text or "pub" in low_text or "tavern" in low_text:
        return "bar"
    if "casual dining" in low_text or "sit down" in low_text or "sit-down" in low_text or "big dining room" in low_text:
        return "casual_dining"
    return "fast_casual"


def _keyword_fallback(text: str) -> ConceptProfile:
    """Deterministic parse used when the LLM is unavailable or never validates. Draws
    only from ingest/cuisine_taxonomy.yaml and the description text -- never invents a
    number beyond the taxonomy's own defaults."""
    taxonomy = _load_taxonomy()
    low = text.lower()
    cuisine_key, cuisine = _match_cuisine(low, taxonomy)
    service_format = _match_service_format(low)

    price_tier = cuisine["default_price_tier"]
    if service_format == "fine_dining":
        price_tier = max(price_tier, 3)
    catchment = cuisine["default_catchment"]

    return ConceptProfile(
        concept_name=text.strip()[:60] or cuisine_key.replace("_", " ").title(),
        cuisines=[cuisine_key],
        substitute_cuisines=list(cuisine.get("substitutes", [])),
        complementary_cuisines=list(cuisine.get("complementary", [])),
        service_format=service_format,
        price_tier=price_tier,
        avg_ticket_usd=AVG_TICKET_BY_TIER[price_tier],
        dayparts=dict(cuisine["default_dayparts"]),
        customer_archetypes=["young_adults"],
        income_fit="medium",
        catchment=catchment,
        catchment_tau_min=TAU_MIN_BY_CATCHMENT[catchment],
        footprint_sqft=(800, 1800),
        seats=30,
        supplier_types=list(cuisine["supplier_types"]),
        direct_competitor_description=f"{cuisine_key.replace('_', ' ')} restaurants similar to: {text.strip()}",
        is_franchise=False,
        proposed_weights=WEIGHTS_BY_FORMAT[service_format],
        confidence=0.3,
        clarifying_questions=[
            "The LLM was unavailable, so this profile was inferred from keywords only -- "
            "please confirm cuisine, price tier, and service format."
        ],
    )


def parse(text: str) -> ConceptProfile:
    prompt = PROMPT_TEMPLATE.format(text=text)
    result = llm_client.generate_structured("concept_parse", cache_input=text, prompt=prompt,
                                             schema=LLMConceptProfile)
    if result is not None:
        return to_concept_profile(result)
    return _keyword_fallback(text)
