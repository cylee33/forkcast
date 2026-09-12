"""Private, optional API surface for the historical popularity model."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.models import ConceptProfile
from ml.popularity import popularity_available, score_profile

router = APIRouter(prefix="/api", tags=["historical-popularity"])


class PopularityRequest(BaseModel):
    profile: ConceptProfile
    h3_ids: list[str] = Field(min_length=1, max_length=5_000)


class PopularityCell(BaseModel):
    h3: str
    historical_popularity_log: float
    historical_popularity_pct: float = Field(ge=0, le=100)
    demographic_missing_count: int = Field(ge=0)
    outside_training_range_count: int = Field(ge=0)


class PopularityResponse(BaseModel):
    status: Literal["experimental_unvalidated_region"]
    model: str
    warning: str
    supported_cuisines: list[str]
    unsupported_cuisines: list[str]
    cells: list[PopularityCell]


class PopularityStatus(BaseModel):
    available: bool
    role: Literal["optional historical online-popularity signal"]
    pittsburgh_validation: Literal["unavailable"]


@router.get("/popularity/status", response_model=PopularityStatus)
def get_popularity_status() -> PopularityStatus:
    return PopularityStatus(
        available=popularity_available(),
        role="optional historical online-popularity signal",
        pittsburgh_validation="unavailable",
    )


@router.post("/popularity", response_model=PopularityResponse)
def score_historical_popularity(request: PopularityRequest) -> PopularityResponse:
    if not popularity_available():
        raise HTTPException(status_code=503, detail="Local popularity artifacts are unavailable")
    try:
        scored = score_profile(request.profile, request.h3_ids)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return PopularityResponse(
        status="experimental_unvalidated_region",
        model=str(scored.attrs["model"]),
        warning=str(scored.attrs["warning"]),
        supported_cuisines=list(scored.attrs["supported_cuisines"]),
        unsupported_cuisines=list(scored.attrs["unsupported_cuisines"]),
        cells=[
            PopularityCell(
                h3=str(row.h3),
                historical_popularity_log=float(row.predicted_log_popularity),
                historical_popularity_pct=float(row.popularity_pct),
                demographic_missing_count=int(row.demographic_missing_count),
                outside_training_range_count=int(row.outside_training_range_count),
            )
            for row in scored.itertuples(index=False)
        ],
    )
