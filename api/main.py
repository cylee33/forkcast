"""Forkcast FastAPI application."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from api.popularity import router as popularity_router

ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="Forkcast API", version="0.1.0")
app.include_router(popularity_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def prototype() -> FileResponse:
    return FileResponse(ROOT / "web/prototype/index.html")


@app.get("/data/fixtures/recommend_sample.json", include_in_schema=False)
def fixture() -> FileResponse:
    return FileResponse(ROOT / "data/fixtures/recommend_sample.json")
