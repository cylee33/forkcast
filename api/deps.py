"""FastAPI dependency providers, shared across routers.

Each `get_*` provider for a module owned by another track (`api/scoring/`, `api/services/`)
does its import inside the function body rather than at module load time. That keeps
`api/main.py` importable -- and `make test` green -- even before those modules exist: nothing
here fails at import time, and `tests/test_api.py` swaps every provider out via
`app.dependency_overrides` before a route ever calls the real one. Once a module is written,
Python caches it in `sys.modules` on first import, so every later call is a cheap dict lookup,
not a re-import or a re-read of the on-disk feature store -- `api/main.py`'s startup hook
triggers that first import eagerly so it happens once at process start, not on the first
request.
"""
import json
import os
import pathlib
from collections.abc import Callable
from functools import lru_cache

import jsonschema
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from api.models import SUBSCORE_KEYS

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"
DATABASE_URL_DEFAULT = "postgresql+psycopg://forkcast:forkcast@localhost:5432/forkcast"

MAX_WEIGHT = 0.4


@lru_cache
def get_db_engine() -> Engine:
    """One SQLAlchemy engine (connection pool) per process, created on first use and reused
    across every request -- never a fresh `create_engine` per request."""
    return create_engine(os.environ.get("DATABASE_URL", DATABASE_URL_DEFAULT))


def get_analyze() -> Callable:
    from api.scoring.engine import analyze
    return analyze


def get_concept_parser() -> Callable:
    from api.services.concept_parser import parse
    return parse


def get_refiner() -> Callable:
    from api.services.refine import refine
    return refine


def get_explainer() -> Callable:
    from api.services.explainer import explain
    return explain


def get_reverser() -> Callable:
    from api.services.reverse import reverse
    return reverse


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Validate LLM-proposed subscore weights, clamp any single weight to <= 0.4 (an LLM
    handing back a weighting where one factor dominates everything else is a degenerate,
    not a legitimate, answer), then renormalize over exactly `SUBSCORE_KEYS` so the final
    weights sum to 1.0. Raises ValueError on anything malformed -- callers let that surface
    as a 400 (see the `ValueError` exception handler in `api/main.py`)."""
    if not isinstance(weights, dict) or not weights:
        raise ValueError("weights must be a non-empty mapping of subscore key to weight")
    unknown = set(weights) - set(SUBSCORE_KEYS)
    if unknown:
        raise ValueError(f"unknown weight keys {sorted(unknown)}; expected a subset of {SUBSCORE_KEYS}")
    clamped: dict[str, float] = {}
    for key in SUBSCORE_KEYS:
        if key not in weights:
            continue
        v = weights[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"weight for {key!r} must be numeric, got {v!r}")
        if v < 0 or v > 1:
            raise ValueError(f"weight for {key!r} must be in [0, 1], got {v}")
        clamped[key] = min(float(v), MAX_WEIGHT)
    total = sum(clamped.values())
    if total <= 0:
        raise ValueError("weights sum to 0 after clamping; cannot renormalize")
    return {k: v / total for k, v in clamped.items()}


@lru_cache
def _schema(name: str) -> dict:
    return json.loads((CONTRACTS_DIR / name).read_text())


def validate_contract(instance: dict, schema_name: str) -> None:
    """Validate an endpoint's outgoing payload against the frozen `contracts/<schema_name>`.
    A failure here means our own response is malformed, not that the caller sent bad input,
    so it is reported as a clean 500 rather than a 4xx."""
    try:
        jsonschema.validate(instance, _schema(schema_name))
    except jsonschema.ValidationError as e:
        raise HTTPException(500, f"response failed contract {schema_name}: {e.message}") from e
