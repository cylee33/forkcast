"""POST /api/reverse -- lat/lng (+ sqft, rent) -> top-N concept suggestions for a pin."""
from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, confloat, conint

from api.deps import get_reverser

router = APIRouter(prefix="/api/reverse", tags=["reverse"])


class ReverseRequest(BaseModel):
    lat: float
    lng: float
    sqft: conint(gt=0) | None = None
    rent: confloat(ge=0) | None = None
    top_n: conint(gt=0, le=8) = 8


class ReverseResponse(BaseModel):
    results: list[dict]


@router.post("", response_model=ReverseResponse)
def reverse_lookup(body: ReverseRequest, reverse_fn: Callable = Depends(get_reverser)) -> ReverseResponse:
    results = reverse_fn(body.lat, body.lng, sqft=body.sqft, rent=body.rent, top_n=body.top_n)
    return ReverseResponse(results=results)
