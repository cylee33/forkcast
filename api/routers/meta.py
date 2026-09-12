"""GET /api/meta -- backtest rho/N (null until a backtest is actually run), data freshness
from parquet mtimes, and the model names in use. Nothing here is estimated or guessed: an
absent backtest reports `null`, not a placeholder number."""
import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from api.deps import get_db_engine

router = APIRouter(prefix="/api/meta", tags=["meta"])

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data/processed"
FRESHNESS_FILES = ["cell_features.parquet", "places.parquet", "geo_cells.parquet"]
MODEL_NAMES = {"concept_parser": "gemini-3.8-flash", "embeddings": "gemini-embedding-001"}


class MetaResponse(BaseModel):
    backtest_rho: float | None
    backtest_n: int | None
    data_freshness: dict[str, str | None]
    models: dict[str, str]


def _mtime_iso(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


@router.get("", response_model=MetaResponse)
def get_meta() -> MetaResponse:
    rho, n = None, None
    try:
        with get_db_engine().connect() as con:
            row = con.execute(text(
                "SELECT rho, n FROM backtest_results ORDER BY created_at DESC LIMIT 1")).first()
        if row is not None:
            rho, n = row[0], row[1]
    except OperationalError:
        pass  # no live DB reachable here -- honestly report "no backtest" rather than fail the request
    return MetaResponse(
        backtest_rho=rho, backtest_n=n,
        data_freshness={f.removesuffix(".parquet"): _mtime_iso(PROCESSED / f) for f in FRESHNESS_FILES},
        models=MODEL_NAMES,
    )
