"""Machine-learning helpers that remain separate from deterministic opportunity scoring."""

from ml.popularity import (
    enrich_cell_collection,
    model_info,
    popularity_available,
    score_popularity,
    score_profile,
)

__all__ = [
    "enrich_cell_collection",
    "model_info",
    "popularity_available",
    "score_popularity",
    "score_profile",
]
