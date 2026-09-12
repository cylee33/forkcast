"""Forkcast API -- FastAPI app wiring CORS, clean error responses, a startup warm-up, and routers.

Scoring is deterministic NumPy over in-memory `cell_features`/`places`; the LLM never ranks.
This module does not implement any of that -- it only validates, dispatches to the scoring/
services modules, persists, and shapes errors. See `api/routers/` for the endpoints and
`api/deps.py` for how those modules are wired in without api/ needing to import them eagerly.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import analysis, concept, explain, meta, reverse

logger = logging.getLogger("forkcast.api")

# Modules other tracks are building in parallel (api/scoring/, api/services/). Importing them
# here at startup -- rather than only lazily, on first request, inside api/deps.py's provider
# functions -- makes sure whatever module-level caching they do (e.g. reading the cell_features
# feature store once) happens once per process at startup, not once per request, without api/
# needing to know how that caching works. A module that isn't finished yet is logged and
# skipped so the app still starts; a route that needs it then returns a clean 5xx (via the
# handlers below) instead of a stack trace.
WARM_IMPORTS = [
    "api.scoring.engine",
    "api.services.concept_parser",
    "api.services.refine",
    "api.services.explainer",
    "api.services.reverse",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    for mod in WARM_IMPORTS:
        try:
            __import__(mod)
        except ImportError as e:
            logger.warning("startup: %s not yet available (%s)", mod, e)
    yield


app = FastAPI(title="Forkcast API", lifespan=lifespan)

# Open to any localhost port: a Streamlit app (default :8501) and, potentially, a Next.js dev
# server (default :3000) both call this from the same machine during development.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _problem(status_code: int, message: str) -> JSONResponse:
    """A clean JSON problem body -- never a stack trace -- for every error path."""
    return JSONResponse(status_code=status_code, content={"error": message})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _problem(422, f"invalid request: {exc.errors()}")


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return _problem(400, str(exc))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return _problem(500, "internal error")


app.include_router(concept.router)
app.include_router(analysis.router)
app.include_router(explain.router)
app.include_router(reverse.router)
app.include_router(meta.router)
