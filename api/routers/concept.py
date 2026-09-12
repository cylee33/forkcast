"""POST /api/concept/parse and POST /api/concept/refine."""
from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_concept_parser, get_refiner, validate_contract
from api.models import ConceptProfile

router = APIRouter(prefix="/api/concept", tags=["concept"])

CONCEPT_PROFILE_SCHEMA = "concept_profile.json"


class ParseRequest(BaseModel):
    text: str


class RefineRequest(BaseModel):
    profile: ConceptProfile
    instruction: str


class RefineResponse(BaseModel):
    profile: ConceptProfile
    diff: dict


@router.post("/parse", response_model=ConceptProfile)
def parse_concept(body: ParseRequest, parse_fn: Callable = Depends(get_concept_parser)) -> ConceptProfile:
    profile = parse_fn(body.text)
    validate_contract(profile.model_dump(mode="json"), CONCEPT_PROFILE_SCHEMA)
    return profile


@router.post("/refine", response_model=RefineResponse)
def refine_concept(body: RefineRequest, refine_fn: Callable = Depends(get_refiner)) -> RefineResponse:
    profile, diff = refine_fn(body.profile, body.instruction)
    validate_contract(profile.model_dump(mode="json"), CONCEPT_PROFILE_SCHEMA)
    return RefineResponse(profile=profile, diff=diff)
