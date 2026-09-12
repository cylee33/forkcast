"""Regression: ingest scripts must not drop schema constraints when writing to real tables.

`ingest/common.write_table(df, name)` defaults to if_exists="replace", which drops and recreates
the table from the DataFrame's dtypes -- discarding every constraint the schema DDL declared
(PRIMARY KEY, NOT NULL, foreign keys, indexes). 04_osm_pois.py and 07_besttime.py write directly
to the real `suppliers` and `place_activity` tables; both must stage the rows and move them with
DELETE/INSERT -- the pattern 00_grid.py and 05_google_places.py already establish -- so the real
table's DDL survives every run.

These tests need the docker-compose db (see `db_engine` in conftest.py); they skip, not fail,
when it isn't reachable.
"""
import pytest
from sqlalchemy import text

from ingest import common
from tests.conftest import load_script


def _constraint_names(engine, table):
    with engine.connect() as con:
        rows = con.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"), {"t": table}
        ).fetchall()
    return {r[0] for r in rows}


def test_write_suppliers_db_preserves_primary_key(db_engine):
    osm = load_script("04_osm_pois")
    before = _constraint_names(db_engine, "suppliers")
    assert "suppliers_pkey" in before, "suppliers must already have its declared primary key"

    osm.write_suppliers_db(common.load("suppliers"))

    after = _constraint_names(db_engine, "suppliers")
    assert "suppliers_pkey" in after, (
        "suppliers lost its primary key after write_suppliers_db -- it must stage+move rows "
        "instead of calling write_table(df, 'suppliers') directly, which replaces the table"
    )

    # idempotent rerun must not raise on the primary key or duplicate rows
    osm.write_suppliers_db(common.load("suppliers"))
    with db_engine.connect() as con:
        n = con.execute(text("SELECT count(*) FROM suppliers")).scalar()
        n_distinct = con.execute(text("SELECT count(DISTINCT id) FROM suppliers")).scalar()
    assert n == n_distinct


def test_write_place_activity_db_preserves_constraints(db_engine):
    bt = load_script("07_besttime")
    with db_engine.connect() as con:
        existing_place = con.execute(text("SELECT id FROM places LIMIT 1")).scalar()
    if existing_place is None:
        pytest.skip("no rows in `places` to satisfy place_activity's foreign key")

    before = _constraint_names(db_engine, "place_activity")
    assert {"place_activity_pkey", "place_activity_place_id_fkey"} <= before

    pa = bt.place_activity_frame([{"place_id": existing_place, "daypart": "lunch", "busyness": 1.0}])
    try:
        bt.write_place_activity_db(pa)
        after = _constraint_names(db_engine, "place_activity")
        assert {"place_activity_pkey", "place_activity_place_id_fkey"} <= after, (
            "place_activity lost its constraints after write_place_activity_db -- it must "
            "stage+move rows instead of calling write_table(pa, 'place_activity') directly"
        )
        # idempotent rerun must not raise on the primary key
        bt.write_place_activity_db(pa)
    finally:
        with db_engine.begin() as con:
            con.execute(text("DELETE FROM place_activity"))
