"""Machine-learning helpers that remain separate from deterministic opportunity scoring."""

from ml.popularity import model_info, score_popularity, score_profile

__all__ = ["model_info", "score_popularity", "score_profile"]
