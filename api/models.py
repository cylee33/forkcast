from typing import Literal

from pydantic import BaseModel, Field, conint, confloat

SUBSCORE_KEYS = ["D", "C", "T", "A", "S_spend", "K", "Sup"]

ServiceFormat = Literal["quick_service", "fast_casual", "casual_dining", "fine_dining", "bar", "cafe", "ghost_kitchen"]
IncomeFit = Literal["low", "low_to_medium", "medium", "medium_to_high", "high"]
Catchment = Literal["walk", "transit", "drive"]
Archetype = Literal["students", "young_adults", "office_workers", "families", "tourists", "nightlife"]


class ConceptProfile(BaseModel):
    concept_name: str
    cuisines: list[str]
    subcuisine: list[str] = []
    substitute_cuisines: list[str] = []
    complementary_cuisines: list[str] = []
    service_format: ServiceFormat
    price_tier: conint(ge=1, le=4)
    avg_ticket_usd: confloat(ge=0)
    dayparts: dict[str, confloat(ge=0, le=1)]
    customer_archetypes: list[Archetype]
    target_age_mix: dict[str, float] = {}
    dine_in_importance: confloat(ge=0, le=1) = 0.5
    takeout_importance: confloat(ge=0, le=1) = 0.5
    delivery_importance: confloat(ge=0, le=1) = 0.3
    parking_importance: confloat(ge=0, le=1) = 0.3
    pedestrian_importance: confloat(ge=0, le=1) = 0.5
    transit_importance: confloat(ge=0, le=1) = 0.3
    nightlife_importance: confloat(ge=0, le=1) = 0.2
    office_importance: confloat(ge=0, le=1) = 0.3
    university_importance: confloat(ge=0, le=1) = 0.2
    family_importance: confloat(ge=0, le=1) = 0.3
    visibility_importance: confloat(ge=0, le=1) = 0.5
    income_fit: IncomeFit
    catchment: Catchment
    catchment_tau_min: confloat(ge=1)
    footprint_sqft: tuple[int, int]
    seats: conint(ge=0)
    supplier_types: list[str]
    direct_competitor_description: str
    is_franchise: bool
    proposed_weights: dict[str, float]
    confidence: confloat(ge=0, le=1)
    clarifying_questions: list[str] = []


class Competitor(BaseModel):
    id: str
    name: str
    distance_m: float
    similarity: float
    rating: float | None
    reviews: int | None


class Anchor(BaseModel):
    name: str
    type: str
    distance_m: float


class Zone(BaseModel):
    zone_id: int
    name: str
    total: float
    best_h3: str
    subscores: dict[str, float | None]
    confidence: float
    drivers: list[str] = Field(max_length=3)
    risks: list[str] = Field(max_length=2)
    gap: dict[str, float]
    gap_flag: bool
    competitors_direct: list[Competitor] = Field(max_length=5)
    competitors_indirect: list[Competitor] = Field(max_length=5)
    anchors: list[Anchor] = Field(max_length=5)
    est_rent_psf_yr: float | None
    rent_confidence: float | None


class RecommendResponse(BaseModel):
    analysis_id: str
    profile: ConceptProfile
    weights: dict[str, float]
    cells: dict  # GeoJSON FeatureCollection
    zones: list[Zone]
    backtest_rho: float | None
