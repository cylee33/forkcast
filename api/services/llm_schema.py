"""A Gemini-structured-output-safe mirror of ConceptProfile.

The Gemini Developer API's structured-output schema converter rejects any JSON schema
with `additionalProperties` (google.genai._transformers._raise_for_unsupported_mldev_properties),
which is exactly what pydantic emits for ConceptProfile's open-keyed `dict[str, float]` fields
(dayparts, proposed_weights). This module re-shapes those two fields as fixed-key sub-models --
their keys are already a closed set per contracts/concept_profile.json -- so response_schema
works against the free-tier API. `to_concept_profile` converts the result back into the real
`ConceptProfile` (never redefined; api/models.py is the single source of truth), dropping any
key the model left null."""
from pydantic import BaseModel, Field

from api.models import Archetype, Catchment, ConceptProfile, IncomeFit, ServiceFormat


class LLMDayparts(BaseModel):
    breakfast: float | None = None
    lunch: float | None = None
    dinner: float | None = None
    late_night: float | None = None
    weekend: float | None = None


class LLMWeights(BaseModel):
    D: float | None = None
    C: float | None = None
    T: float | None = None
    A: float | None = None
    S_spend: float | None = None
    K: float | None = None
    Sup: float | None = None


class LLMConceptProfile(BaseModel):
    concept_name: str
    cuisines: list[str]
    subcuisine: list[str] = []
    substitute_cuisines: list[str] = []
    complementary_cuisines: list[str] = []
    service_format: ServiceFormat
    price_tier: int
    avg_ticket_usd: float
    dayparts: LLMDayparts
    customer_archetypes: list[Archetype]
    dine_in_importance: float = 0.5
    takeout_importance: float = 0.5
    delivery_importance: float = 0.3
    parking_importance: float = 0.3
    pedestrian_importance: float = 0.5
    transit_importance: float = 0.3
    nightlife_importance: float = 0.2
    office_importance: float = 0.3
    university_importance: float = 0.2
    family_importance: float = 0.3
    visibility_importance: float = 0.5
    income_fit: IncomeFit
    catchment: Catchment
    catchment_tau_min: float
    footprint_sqft: list[int] = Field(min_length=2, max_length=2)
    seats: int
    supplier_types: list[str]
    direct_competitor_description: str
    is_franchise: bool
    proposed_weights: LLMWeights
    confidence: float
    clarifying_questions: list[str] = []


def _strip_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def to_concept_profile(llm: LLMConceptProfile) -> ConceptProfile:
    data = llm.model_dump(exclude={"dayparts", "proposed_weights"})
    data["dayparts"] = _strip_none(llm.dayparts.model_dump())
    data["proposed_weights"] = _strip_none(llm.proposed_weights.model_dump())
    return ConceptProfile(**data)


def from_concept_profile(profile: ConceptProfile) -> LLMConceptProfile:
    """Seeds refine()'s "current profile" view of a real ConceptProfile for the prompt."""
    data = profile.model_dump(exclude={"dayparts", "proposed_weights", "target_age_mix"})
    data["dayparts"] = LLMDayparts(**profile.dayparts)
    data["proposed_weights"] = LLMWeights(**profile.proposed_weights)
    return LLMConceptProfile(**data)
