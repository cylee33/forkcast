"""POST /api/explain -- Why-Here narrative text for one zone."""
from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_explainer
from api.models import ConceptProfile

router = APIRouter(prefix="/api/explain", tags=["explain"])


class ExplainRequest(BaseModel):
    profile: ConceptProfile
    zone: dict


class ExplainResponse(BaseModel):
    text: str


@router.post("", response_model=ExplainResponse)
def explain_zone(body: ExplainRequest, explain_fn: Callable = Depends(get_explainer)) -> ExplainResponse:
    # explain_fn receives only the already-computed numbers in `body.zone` -- the explainer
    # module is responsible for never inventing a figure beyond them; this endpoint just
    # forwards the profile and zone dict through.
    return ExplainResponse(text=explain_fn(body.profile, body.zone))
