"""Forkcast FastAPI application."""

from fastapi import FastAPI

from api.popularity import router as popularity_router

app = FastAPI(title="Forkcast API", version="0.1.0")
app.include_router(popularity_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
