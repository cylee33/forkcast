"""HTTP client for the Forkcast FastAPI service.

The app never imports `api/scoring` or `api/services` - every operation goes over HTTP so
the API is genuinely exercised. Base URL comes from `FORKCAST_API`, defaulting to
`http://localhost:8000`. When the service is unreachable, callers fall back to the
committed fixture (`data/fixtures/recommend_sample.json`) so the app still runs
standalone; `get_analysis` below is the one call site that performs that fallback for the
main forward-mode flow.

Request body shapes for `/api/concept/parse`, `/api/concept/refine`, `/api/analysis`,
`/api/explain`, and `/api/reverse` are not yet frozen contracts (only the *response*
schema, `contracts/recommend_response.json`, is) - the shapes below follow
`brain/architecture.md`'s endpoint table as closely as it specifies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "recommend_sample.json"
DEFAULT_BASE_URL = "http://localhost:8000"
REQUEST_TIMEOUT_S = 5


class ApiUnavailable(Exception):
    """Raised when the FastAPI service cannot be reached, times out, or returns an error
    status. Callers decide whether to fall back or surface the failure."""


def get_base_url() -> str:
    return os.environ.get("FORKCAST_API", DEFAULT_BASE_URL).rstrip("/")


def load_fixture() -> dict[str, Any]:
    """Load the committed, schema-valid `RecommendResponse` fixture."""
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{get_base_url()}{path}"
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise ApiUnavailable(f"POST {path} failed: {e}") from e


def _get(path: str) -> dict[str, Any]:
    url = f"{get_base_url()}{path}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise ApiUnavailable(f"GET {path} failed: {e}") from e


def check_api_up() -> bool:
    try:
        _get("/api/meta")
        return True
    except ApiUnavailable:
        return False


def parse_concept(text: str) -> dict[str, Any]:
    """POST /api/concept/parse -> ConceptProfile."""
    return _post("/api/concept/parse", {"text": text})


def refine_concept(profile: dict[str, Any], instruction: str) -> dict[str, Any]:
    """POST /api/concept/refine -> {"profile": ConceptProfile, "diff": [...]} (or an
    equivalent patched-profile shape; the app treats any dict with a "profile" key, else
    the whole payload, as the new profile - see `state.apply_refine_response`)."""
    return _post("/api/concept/refine", {"profile": profile, "instruction": instruction})


def run_analysis(
    profile: dict[str, Any],
    center: dict[str, float],
    radius_mi: float,
    rent_ceiling_psf_yr: float | None = None,
) -> dict[str, Any]:
    """POST /api/analysis -> RecommendResponse."""
    payload: dict[str, Any] = {"profile": profile, "center": center, "radius_mi": radius_mi}
    if rent_ceiling_psf_yr is not None:
        payload["rent_ceiling_psf_yr"] = rent_ceiling_psf_yr
    return _post("/api/analysis", payload)


def explain_zone(profile: dict[str, Any], zone: dict[str, Any]) -> dict[str, Any]:
    """POST /api/explain -> Why-Here narrative."""
    return _post("/api/explain", {"profile": profile, "zone": zone})


def reverse_lookup(
    lat: float,
    lng: float,
    sqft: float | None = None,
    rent: float | None = None,
) -> dict[str, Any]:
    """POST /api/reverse -> top concepts for a point."""
    payload: dict[str, Any] = {"lat": lat, "lng": lng}
    if sqft is not None:
        payload["sqft"] = sqft
    if rent is not None:
        payload["rent"] = rent
    return _post("/api/reverse", payload)


def get_meta() -> dict[str, Any]:
    """GET /api/meta -> backtest rho, N, data freshness, model names."""
    return _get("/api/meta")


START_HINT = "Start it with `uvicorn api.main:app --reload --port 8000` and rerun."


def get_analysis(
    profile: dict[str, Any],
    center: dict[str, float],
    radius_mi: float,
    rent_ceiling_psf_yr: float | None = None,
) -> tuple[dict[str, Any], str, str | None]:
    """Try the live API for an already-parsed profile; on any failure, fall back to the
    fixture (used for re-running after a profile-chip edit or a refine).

    Returns `(response, source, message)` where `source` is `"api"` or `"fixture"` and
    `message` is a short, non-alarming explanation to show the user when a fallback
    happened (`None` when the live call succeeded).
    """
    try:
        data = run_analysis(profile, center, radius_mi, rent_ceiling_psf_yr)
        return data, "api", None
    except ApiUnavailable as e:
        fixture = dict(load_fixture())
        fixture["profile"] = profile
        return (
            fixture,
            "fixture",
            f"Showing fixture data - the API at {get_base_url()} is unreachable ({e}). {START_HINT}",
        )


def analyze_concept(
    concept_text: str,
    center: dict[str, float],
    radius_mi: float,
    rent_ceiling_psf_yr: float | None = None,
) -> tuple[dict[str, Any], str, str | None]:
    """Full forward-mode flow from free text: parse the concept, then analyze it.

    Falls back to the fixture at either step. Returns the same
    `(response, source, message)` shape as `get_analysis`.
    """
    try:
        profile = parse_concept(concept_text)
    except ApiUnavailable as e:
        return (
            load_fixture(),
            "fixture",
            f"Showing fixture data - the API at {get_base_url()} is unreachable, so "
            f"'{concept_text}' could not be parsed ({e}). {START_HINT}",
        )
    return get_analysis(profile, center, radius_mi, rent_ceiling_psf_yr)


def explain_or_fallback(profile: dict[str, Any], zone: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Try /api/explain; on failure, fall back to an honest narrative built only from the
    zone's own computed fields (no invented narration). Returns `(response, source)` with
    `source` in `{"api", "fallback"}`; a fallback response always carries a "text" key."""
    try:
        return explain_zone(profile, zone), "api"
    except ApiUnavailable:
        lines = [f"- {d}" for d in zone.get("drivers", [])]
        text = "Why here (computed drivers - narration needs the API):\n" + "\n".join(lines)
        risks = zone.get("risks") or []
        if risks:
            text += "\n\nRisks:\n" + "\n".join(f"- {r}" for r in risks)
        return {"text": text}, "fallback"
