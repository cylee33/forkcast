import pathlib

SQL = (pathlib.Path(__file__).resolve().parents[1] / "docker/db/init/01_schema.sql").read_text()


def test_schema_has_all_tables():
    for t in ["geo_cells", "cell_features", "places", "place_activity", "suppliers",
              "analyses", "analysis_cells", "concept_cache", "zone_names", "backtest_results"]:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in SQL


def test_schema_enables_extensions():
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in SQL
    assert "CREATE EXTENSION IF NOT EXISTS vector" in SQL
