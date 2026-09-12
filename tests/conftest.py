import importlib.util
import pathlib
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest import common  # noqa: E402


def load_script(stem: str):
    """Import ingest/<stem>.py (digit-prefixed names can't be imported normally)."""
    path = ROOT / "ingest" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db_engine():
    """Live Postgres engine for tests that check real schema/constraints against the docker-compose
    db. Skips (rather than fails) when the db isn't reachable, since the suite must run without one."""
    eng = common.engine()
    try:
        with eng.connect() as con:
            con.execute(text("SELECT 1"))
    except OperationalError as e:
        pytest.skip(f"no live database: {e}")
    return eng
