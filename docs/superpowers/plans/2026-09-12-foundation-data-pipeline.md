# Forkcast Foundation (Track A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the repo skeleton, frozen contracts, shared team files, and the complete Pittsburgh data pipeline that produces `cell_features`, `places`, embeddings, and fixtures, so Dev 2 (backend) and Dev 3 (web) can start in parallel.

**Architecture:** Thirteen idempotent Python ingest scripts read raw sources into `data/raw/`, write parquet to `data/processed/`, and upsert Postgres (PostGIS + pgvector) tables. A shared `ingest/common.py` owns paths, DB access, H3 helpers, and area weighting. `12_build_features.py` joins everything into one `cell_features` table with metro-wide percentiles. Contracts in `contracts/` are mirrored by `api/models.py` (Pydantic) and `web/lib/types.ts`.

**Tech Stack:** Python 3.11, pandas, geopandas, shapely, h3 (v4), SQLAlchemy + psycopg, requests, pyyaml, voyageai; Postgres 16 + PostGIS 3.4 + pgvector via Docker; pytest + ruff; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-12-forkcast-design.md` (and `forkcast-proposal.md` for formulas).

## Global Constraints

- Spatial unit: H3 resolution 9 over Allegheny County, PA (FIPS 42003).
- Every ingest script is idempotent, accepts `--limit N`, reads `data/raw/`, writes `data/processed/<name>.parquet`, upserts the DB.
- `data/raw/` is gitignored. `data/fixtures/` is always committed.
- No ACS ancestry or foreign-born tables. No scraping of Google Maps, Yelp, LoopNet, Crexi.
- Google Places calls are county-wide, field-masked, cached to raw JSON. Never per-hex calls at request time.
- Every `cell_features` row carries `source`, `resolution`, `updated_at`.
- Embedding model: Voyage `voyage-3` (1024 dims). LLM: `claude-sonnet-5` (not used in this plan).
- Commit after every completed task. Push to `origin main` at least at the end of every task group.
- Do not create or edit `README.md` (project rule; user permission required).
- `.env` holds `DATABASE_URL`, `CENSUS_API_KEY`, `GOOGLE_PLACES_API_KEY`, `BESTTIME_API_KEY_PRIVATE`, `VOYAGE_API_KEY`, `WPRDC_FOOD_RESOURCE_ID`.

---

## File Structure

```
forkcast/
  pyproject.toml                 # ruff config
  requirements.txt               # python deps for ingest + tests
  Makefile                       # db-up, ingest, ingest STEP=NN, test, fixtures, restore-data
  docker-compose.yml             # db, api (placeholder), web (placeholder)
  docker/db/Dockerfile           # postgis + pgvector
  docker/db/init/01_schema.sql   # all tables
  .env.example
  .github/workflows/ci.yml
  contracts/
    concept_profile.json
    recommend_response.json
    cell_features.md
    places.md
  api/models.py                  # Pydantic mirror of contracts (backend track fills the rest)
  web/lib/types.ts               # TS mirror of contracts (web track fills the rest)
  ingest/
    common.py                    # paths, engine, cells, area weighting, percentiles, cli
    00_grid.py … 12_build_features.py, sanity.py, make_fixtures.py
    cuisine_taxonomy.yaml
    cex_food_away.yaml
  data/
    raw/                         # gitignored
    processed/                   # parquet
    fixtures/                    # cell_features_sample.parquet, recommend_sample.json, raw_sample/
    rents_manual.csv             # hand-collected asking rents (committed)
  tests/
    conftest.py
    test_contracts.py
    test_common.py
    test_grid.py
    test_acs.py
    test_lodes.py
    test_wprdc.py
    test_osm.py
    test_google.py
    test_besttime.py
    test_spend.py
    test_rent.py
    test_affinity.py
    test_build_features.py
  brain/  (plan, tasks, progress, lessons, architecture, team, demo)
  .claude/agents/ (data-ingest.md, backend.md, frontend.md, qa.md)
```

Ingest scripts are named with leading digits, so they are imported in tests via `importlib` (helper in `tests/conftest.py`).

---

### Task 1: Repo skeleton, Docker DB, schema, CI

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `Makefile`, `docker-compose.yml`, `docker/db/Dockerfile`, `docker/db/init/01_schema.sql`, `.env.example`, `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/test_schema.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `DATABASE_URL` env convention `postgresql+psycopg://forkcast:forkcast@localhost:5432/forkcast`; tables listed in `01_schema.sql`; `tests/conftest.py::load_script(name)` returning a module for `ingest/NN_name.py`.

- [ ] **Step 1: Write requirements and ruff config**

`requirements.txt`:
```
pandas==2.2.2
pyarrow==17.0.0
geopandas==1.0.1
shapely==2.0.6
h3==4.1.2
SQLAlchemy==2.0.36
psycopg[binary]==3.2.3
requests==2.32.3
pyyaml==6.0.2
voyageai==0.3.2
numpy==1.26.4
scipy==1.14.1
matplotlib==3.9.2
python-dotenv==1.0.1
pytest==8.3.3
ruff==0.6.9
```

`pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
target-version = "py311"
extend-exclude = ["web", "data"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write Docker DB image and compose**

`docker/db/Dockerfile`:
```dockerfile
FROM postgis/postgis:16-3.4
RUN apt-get update && apt-get install -y postgresql-16-pgvector && rm -rf /var/lib/apt/lists/*
```

`docker-compose.yml`:
```yaml
services:
  db:
    build: ./docker/db
    environment:
      POSTGRES_USER: forkcast
      POSTGRES_PASSWORD: forkcast
      POSTGRES_DB: forkcast
    ports: ["5432:5432"]
    volumes:
      - ./docker/db/init:/docker-entrypoint-initdb.d:ro
      - dbdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U forkcast"]
      interval: 5s
      retries: 10
volumes:
  dbdata:
```
(`api` and `web` services are added by their tracks.)

- [ ] **Step 3: Write schema**

`docker/db/init/01_schema.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS geo_cells (
  h3 TEXT PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  geom GEOMETRY(Polygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS geo_cells_geom_idx ON geo_cells USING GIST (geom);

CREATE TABLE IF NOT EXISTS cell_features (
  h3 TEXT PRIMARY KEY REFERENCES geo_cells(h3),
  features JSONB NOT NULL,          -- all numeric columns, incl. *_pct
  cuisine_affinity JSONB NOT NULL,  -- {cuisine_key: 0-100}
  activity_by_daypart JSONB NOT NULL,
  traffic_source TEXT NOT NULL,     -- real | proxy
  rent_source TEXT, rent_resolution TEXT, rent_confidence DOUBLE PRECISION,
  source JSONB NOT NULL,            -- {column: source}
  resolution JSONB NOT NULL,        -- {column: resolution}
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS places (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL, provider_id TEXT,
  name TEXT NOT NULL, lat DOUBLE PRECISION NOT NULL, lng DOUBLE PRECISION NOT NULL,
  h3 TEXT NOT NULL,
  categories TEXT[] NOT NULL DEFAULT '{}',
  cuisine_key TEXT, price_level INTEGER, rating DOUBLE PRECISION, reviews INTEGER,
  is_chain BOOLEAN NOT NULL DEFAULT false, is_open BOOLEAN NOT NULL DEFAULT true,
  source TEXT NOT NULL, summary TEXT,
  embedding VECTOR(1024)
);
CREATE INDEX IF NOT EXISTS places_h3_idx ON places (h3);

CREATE TABLE IF NOT EXISTS place_activity (
  place_id TEXT REFERENCES places(id), daypart TEXT NOT NULL, busyness DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (place_id, daypart)
);

CREATE TABLE IF NOT EXISTS suppliers (
  id TEXT PRIMARY KEY, name TEXT, supplier_type TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL, lng DOUBLE PRECISION NOT NULL, h3 TEXT NOT NULL, source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY, concept_json JSONB NOT NULL, weights_json JSONB NOT NULL, model_json JSONB NOT NULL,
  center_lat DOUBLE PRECISION, center_lng DOUBLE PRECISION, radius_mi DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analysis_cells (
  analysis_id TEXT REFERENCES analyses(id), h3 TEXT NOT NULL,
  subscores_json JSONB NOT NULL, total DOUBLE PRECISION NOT NULL, confidence DOUBLE PRECISION NOT NULL, zone_id INTEGER,
  PRIMARY KEY (analysis_id, h3)
);
CREATE TABLE IF NOT EXISTS concept_cache (
  normalized_text TEXT PRIMARY KEY, profile_json JSONB NOT NULL, model TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS zone_names (h3 TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backtest_results (
  id SERIAL PRIMARY KEY, rho DOUBLE PRECISION NOT NULL, n INTEGER NOT NULL, model TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
```

- [ ] **Step 4: Write `.env.example`, Makefile, gitignore additions**

`.env.example`:
```
DATABASE_URL=postgresql+psycopg://forkcast:forkcast@localhost:5432/forkcast
CENSUS_API_KEY=
GOOGLE_PLACES_API_KEY=
BESTTIME_API_KEY_PRIVATE=
VOYAGE_API_KEY=
ANTHROPIC_API_KEY=
WPRDC_FOOD_RESOURCE_ID=
```

`Makefile`:
```makefile
STEPS := 00_grid 01_census_acs 02_lodes 03_wprdc_food 04_osm_pois 05_google_places 07_besttime 08_place_embeddings 09_spend_capacity 10_rent_proxy 11_cuisine_affinity 12_build_features
PY := .venv/bin/python

.PHONY: venv db-up db-down ingest test lint fixtures sanity restore-data

venv:
	python3.11 -m venv .venv && $(PY) -m pip install -r requirements.txt

db-up:
	docker compose up -d db

db-down:
	docker compose down

ingest:
ifdef STEP
	$(PY) ingest/$(STEP)*.py $(ARGS)
else
	for s in $(STEPS); do $(PY) ingest/$$s.py $(ARGS) || exit 1; done
endif

sanity:
	$(PY) ingest/sanity.py

fixtures:
	$(PY) ingest/make_fixtures.py

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check ingest api tests

restore-data:
	unzip -o data/processed.zip -d data/
```

Append to `.gitignore`:
```
data/processed.zip
*.png
!data/fixtures/**
```

- [ ] **Step 5: Write CI**

`.github/workflows/ci.yml`:
```yaml
name: ci
on: [push, pull_request]
jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip }
      - run: pip install -r requirements.txt
      - run: ruff check ingest api tests
      - run: pytest -q
```
(Web job is added by the web track.)

- [ ] **Step 6: Write test helper and a schema test**

`tests/conftest.py`:
```python
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_script(stem: str):
    """Import ingest/<stem>.py (digit-prefixed names can't be imported normally)."""
    path = ROOT / "ingest" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

`tests/test_schema.py`:
```python
import pathlib

SQL = (pathlib.Path(__file__).resolve().parents[1] / "docker/db/init/01_schema.sql").read_text()


def test_schema_has_all_tables():
    for t in ["geo_cells", "cell_features", "places", "place_activity", "suppliers",
              "analyses", "analysis_cells", "concept_cache", "zone_names", "backtest_results"]:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in SQL


def test_schema_enables_extensions():
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in SQL
    assert "CREATE EXTENSION IF NOT EXISTS vector" in SQL
```

- [ ] **Step 7: Create venv, run tests, boot DB**

Run:
```bash
make venv && make test && make db-up && sleep 8 && docker compose exec db psql -U forkcast -c "\dt"
```
Expected: 2 tests pass; `\dt` lists 10 tables.

- [ ] **Step 8: Commit and push**

```bash
git add -A && git commit -m "chore: repo skeleton, docker db with postgis+pgvector, schema, ci" && git push
```

---

### Task 2: Contracts and their Pydantic / TypeScript mirrors

**Files:**
- Create: `contracts/concept_profile.json`, `contracts/recommend_response.json`, `contracts/cell_features.md`, `contracts/places.md`, `api/__init__.py`, `api/models.py`, `web/lib/types.ts`, `tests/test_contracts.py`

**Interfaces:**
- Produces: `api.models.ConceptProfile`, `api.models.RecommendResponse`, `api.models.Zone`, `api.models.SUBSCORE_KEYS = ["D","C","T","A","S_spend","K","Sup"]`; the `cell_features` column list in `contracts/cell_features.md` that Task 15 must emit exactly.

- [ ] **Step 1: Write `contracts/concept_profile.json`** (JSON Schema draft 2020-12; fields from proposal §4)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ConceptProfile",
  "type": "object",
  "required": ["concept_name","cuisines","service_format","price_tier","avg_ticket_usd","dayparts",
               "customer_archetypes","income_fit","catchment","catchment_tau_min","footprint_sqft","seats",
               "supplier_types","direct_competitor_description","is_franchise","proposed_weights","confidence"],
  "properties": {
    "concept_name": {"type":"string"},
    "cuisines": {"type":"array","items":{"type":"string"}},
    "subcuisine": {"type":"array","items":{"type":"string"},"default":[]},
    "substitute_cuisines": {"type":"array","items":{"type":"string"},"default":[]},
    "complementary_cuisines": {"type":"array","items":{"type":"string"},"default":[]},
    "service_format": {"enum":["quick_service","fast_casual","casual_dining","fine_dining","bar","cafe","ghost_kitchen"]},
    "price_tier": {"type":"integer","minimum":1,"maximum":4},
    "avg_ticket_usd": {"type":"number","minimum":0},
    "dayparts": {"type":"object","additionalProperties":{"type":"number","minimum":0,"maximum":1},
                 "propertyNames":{"enum":["breakfast","lunch","dinner","late_night","weekend"]}},
    "customer_archetypes": {"type":"array","items":{"enum":["students","young_adults","office_workers","families","tourists","nightlife"]}},
    "target_age_mix": {"type":"object","additionalProperties":{"type":"number"},"default":{}},
    "dine_in_importance":{"type":"number","minimum":0,"maximum":1,"default":0.5},
    "takeout_importance":{"type":"number","minimum":0,"maximum":1,"default":0.5},
    "delivery_importance":{"type":"number","minimum":0,"maximum":1,"default":0.3},
    "parking_importance":{"type":"number","minimum":0,"maximum":1,"default":0.3},
    "pedestrian_importance":{"type":"number","minimum":0,"maximum":1,"default":0.5},
    "transit_importance":{"type":"number","minimum":0,"maximum":1,"default":0.3},
    "nightlife_importance":{"type":"number","minimum":0,"maximum":1,"default":0.2},
    "office_importance":{"type":"number","minimum":0,"maximum":1,"default":0.3},
    "university_importance":{"type":"number","minimum":0,"maximum":1,"default":0.2},
    "family_importance":{"type":"number","minimum":0,"maximum":1,"default":0.3},
    "visibility_importance":{"type":"number","minimum":0,"maximum":1,"default":0.5},
    "income_fit": {"enum":["low","low_to_medium","medium","medium_to_high","high"]},
    "catchment": {"enum":["walk","transit","drive"]},
    "catchment_tau_min": {"type":"number","minimum":1},
    "footprint_sqft": {"type":"array","items":{"type":"integer"},"minItems":2,"maxItems":2},
    "seats": {"type":"integer","minimum":0},
    "supplier_types": {"type":"array","items":{"type":"string"}},
    "direct_competitor_description": {"type":"string"},
    "is_franchise": {"type":"boolean"},
    "proposed_weights": {"type":"object","additionalProperties":{"type":"number"},
                         "propertyNames":{"enum":["D","C","T","A","S_spend","K","Sup"]}},
    "confidence": {"type":"number","minimum":0,"maximum":1},
    "clarifying_questions": {"type":"array","items":{"type":"string"},"default":[]}
  }
}
```

- [ ] **Step 2: Write `contracts/recommend_response.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RecommendResponse",
  "type": "object",
  "required": ["analysis_id","profile","weights","cells","zones","backtest_rho"],
  "$defs": {
    "subscores": {"type":"object","required":["D","C","T","A","S_spend","K","Sup"],
                  "additionalProperties":{"type":["number","null"]}},
    "competitor": {"type":"object","required":["id","name","distance_m","similarity","rating","reviews"],
                   "properties":{"id":{"type":"string"},"name":{"type":"string"},"distance_m":{"type":"number"},
                                 "similarity":{"type":"number"},"rating":{"type":["number","null"]},"reviews":{"type":["integer","null"]}}},
    "anchor": {"type":"object","required":["name","type","distance_m"],
               "properties":{"name":{"type":"string"},"type":{"type":"string"},"distance_m":{"type":"number"}}},
    "zone": {"type":"object",
      "required":["zone_id","name","total","best_h3","subscores","confidence","drivers","risks","gap","gap_flag",
                  "competitors_direct","competitors_indirect","anchors","est_rent_psf_yr","rent_confidence"],
      "properties":{
        "zone_id":{"type":"integer"},"name":{"type":"string"},"total":{"type":"number"},"best_h3":{"type":"string"},
        "subscores":{"$ref":"#/$defs/subscores"},"confidence":{"type":"number"},
        "drivers":{"type":"array","items":{"type":"string"},"maxItems":3},
        "risks":{"type":"array","items":{"type":"string"},"maxItems":2},
        "gap":{"type":"object","required":["demand","supply","gap"],"additionalProperties":{"type":"number"}},
        "gap_flag":{"type":"boolean"},
        "competitors_direct":{"type":"array","items":{"$ref":"#/$defs/competitor"},"maxItems":5},
        "competitors_indirect":{"type":"array","items":{"$ref":"#/$defs/competitor"},"maxItems":5},
        "anchors":{"type":"array","items":{"$ref":"#/$defs/anchor"},"maxItems":5},
        "est_rent_psf_yr":{"type":["number","null"]},"rent_confidence":{"type":["number","null"]}
      }}
  },
  "properties": {
    "analysis_id":{"type":"string"},
    "profile":{"type":"object"},
    "weights":{"$ref":"#/$defs/subscores"},
    "cells":{"type":"object","required":["type","features"],
             "properties":{"type":{"const":"FeatureCollection"},
                           "features":{"type":"array","items":{"type":"object","required":["type","geometry","properties"],
                             "properties":{"properties":{"type":"object",
                               "required":["h3","total","D","C","T","A","S_spend","K","Sup","confidence","zone_id"]}}}}}},
    "zones":{"type":"array","items":{"$ref":"#/$defs/zone"}},
    "backtest_rho":{"type":["number","null"]}
  }
}
```

- [ ] **Step 3: Write `contracts/cell_features.md`** (the column list Task 15 must emit)

```markdown
# cell_features columns

Stored as `cell_features.features` JSONB and as `data/processed/cell_features.parquet` (one column each).
Every numeric column `X` also has `X_pct` (metro-wide percentile, 0–100). Sources/resolutions live in the
`source` / `resolution` JSONB maps keyed by column name.

| Column | Unit | Source | Resolution |
|---|---|---|---|
| pop_total, hh_count | count | ACS 5yr 2023 | block group, area-weighted |
| median_hh_income | USD | ACS | block group |
| income_lt25k, income_25_50k, income_50_75k, income_75_100k, income_100_150k, income_150k_plus | share 0–1 | ACS B19001 | block group |
| pct_age_18_24, pct_age_25_34, pct_age_35_54, pct_age_55p | share | ACS B01001 | block group |
| pct_families_with_kids | share | ACS B11005 | block group |
| avg_hh_size | persons | ACS B25010 | block group |
| pct_no_vehicle | share | ACS B25044 | block group |
| pct_renters | share | ACS B25003 | block group |
| pct_bachelors_plus | share | ACS B15003 | block group |
| pct_students | share | ACS B14007 (college/grad enrolled) | block group |
| workers_daytime, workers_high_wage | count | LODES WAC 2021 | block group (block rolled up), area-weighted |
| restaurants_open | count | WPRDC + Google | point, grid_disk(1) smoothed |
| anchor_university, anchor_school, anchor_office, anchor_hospital, anchor_hotel, anchor_bar, anchor_nightclub, anchor_mall, anchor_cinema, anchor_stadium, anchor_park, anchor_attraction, anchor_transit_station | count within ~500 m (grid_disk(2)) | OSM | point |
| dist_to_university_km, dist_to_hospital_km, dist_to_transit_station_km, dist_to_stadium_km | km | OSM | point |
| transit_daily_trips | count | GTFS (PRT) stop_times in cell + grid_disk(1) | point |
| main_road_frontage | 0/1 | OSM highway=primary/secondary/tertiary intersects cell | line |
| parking_lots | count | OSM amenity=parking, grid_disk(1) | point |
| walkable_poi_density | count | OSM shops+amenities, grid_disk(2) | point |
| poi_density | count | all OSM POIs in cell | point |
| activity_morning, activity_lunch, activity_afternoon, activity_dinner, activity_late_night, activity_weekend | relative 0–100 | BestTime (real) or proxy | point, distance-weighted |
| traffic_source | real / proxy | — | — |
| spending_capacity | USD/yr food-away-from-home per HH × HH | CEX × ACS | block group |
| local_price_1, local_price_2, local_price_3, local_price_4 | share | Google priceLevel, grid_disk(2) | point |
| est_rent_psf_yr, rent_confidence, rent_source, rent_resolution | USD/sqft/yr, 0–1, text, text | ZORI ZIP + manual rents regression | ZIP |
| dist_to_wholesale_km, dist_to_supermarket_km, dist_to_seafood_km, dist_to_butcher_km, dist_to_greengrocer_km, dist_to_asian_grocer_km, dist_to_italian_grocer_km | km | OSM + hand list | point |
| cuisine_affinity | {cuisine_key: 0–100} | derived (§3.4) | grid_disk(2) |
```

- [ ] **Step 4: Write `contracts/places.md`**

```markdown
# places table

| Column | Notes |
|---|---|
| id | `wprdc:<facility_id>` or `google:<place_id>` when no WPRDC match |
| provider, provider_id | origin row |
| name, lat, lng, h3 | h3 at res 9 |
| categories | text[] from Google `types` + WPRDC description |
| cuisine_key | canonical key from `ingest/cuisine_taxonomy.yaml`, nullable |
| price_level | 1–4 from Google `priceLevel`, nullable |
| rating, reviews | Google `rating`, `userRatingCount`, nullable |
| is_chain | name matches taxonomy `chains` list |
| is_open | WPRDC status open AND Google businessStatus != CLOSED_PERMANENTLY |
| source | `wprdc+google`, `wprdc`, `google` |
| summary | Google editorialSummary text |
| embedding | vector(1024), voyage-3 on `name. categories. summary` |
```

- [ ] **Step 5: Write the failing contract test**

`tests/test_contracts.py`:
```python
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_concept_profile_schema_loads():
    s = json.loads((ROOT / "contracts/concept_profile.json").read_text())
    assert s["title"] == "ConceptProfile"
    assert "proposed_weights" in s["properties"]


def test_pydantic_mirror_matches_schema_required_fields():
    from api.models import ConceptProfile
    s = json.loads((ROOT / "contracts/concept_profile.json").read_text())
    assert set(s["required"]) <= set(ConceptProfile.model_fields)


def test_pydantic_rejects_bad_price_tier():
    from api.models import ConceptProfile
    with pytest.raises(Exception):
        ConceptProfile(concept_name="x", cuisines=["korean"], service_format="cafe", price_tier=9,
                       avg_ticket_usd=10, dayparts={"lunch": 1}, customer_archetypes=["students"],
                       income_fit="low", catchment="walk", catchment_tau_min=8, footprint_sqft=(800, 1500),
                       seats=20, supplier_types=["asian_grocer"], direct_competitor_description="korean",
                       is_franchise=False, proposed_weights={}, confidence=0.9)


def test_subscore_keys():
    from api.models import SUBSCORE_KEYS
    assert SUBSCORE_KEYS == ["D", "C", "T", "A", "S_spend", "K", "Sup"]
```

- [ ] **Step 6: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_contracts.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'api'`.

- [ ] **Step 7: Write `api/models.py`** (add `pydantic==2.9.2` to `requirements.txt`, reinstall)

```python
from typing import Literal

from pydantic import BaseModel, Field, conint, confloat

SUBSCORE_KEYS = ["D", "C", "T", "A", "S_spend", "K", "Sup"]

ServiceFormat = Literal["quick_service", "fast_casual", "casual_dining", "fine_dining", "bar", "cafe", "ghost_kitchen"]
IncomeFit = Literal["low", "low_to_medium", "medium", "medium_to_high", "high"]
Catchment = Literal["walk", "transit", "drive"]
Archetype = Literal["students", "young_adults", "office_workers", "families", "tourists", "nightlife"]


class ConceptProfile(BaseModel):
    concept_name: str
    cuisines: list[str]
    subcuisine: list[str] = []
    substitute_cuisines: list[str] = []
    complementary_cuisines: list[str] = []
    service_format: ServiceFormat
    price_tier: conint(ge=1, le=4)
    avg_ticket_usd: confloat(ge=0)
    dayparts: dict[str, confloat(ge=0, le=1)]
    customer_archetypes: list[Archetype]
    target_age_mix: dict[str, float] = {}
    dine_in_importance: confloat(ge=0, le=1) = 0.5
    takeout_importance: confloat(ge=0, le=1) = 0.5
    delivery_importance: confloat(ge=0, le=1) = 0.3
    parking_importance: confloat(ge=0, le=1) = 0.3
    pedestrian_importance: confloat(ge=0, le=1) = 0.5
    transit_importance: confloat(ge=0, le=1) = 0.3
    nightlife_importance: confloat(ge=0, le=1) = 0.2
    office_importance: confloat(ge=0, le=1) = 0.3
    university_importance: confloat(ge=0, le=1) = 0.2
    family_importance: confloat(ge=0, le=1) = 0.3
    visibility_importance: confloat(ge=0, le=1) = 0.5
    income_fit: IncomeFit
    catchment: Catchment
    catchment_tau_min: confloat(ge=1)
    footprint_sqft: tuple[int, int]
    seats: conint(ge=0)
    supplier_types: list[str]
    direct_competitor_description: str
    is_franchise: bool
    proposed_weights: dict[str, float]
    confidence: confloat(ge=0, le=1)
    clarifying_questions: list[str] = []


class Competitor(BaseModel):
    id: str
    name: str
    distance_m: float
    similarity: float
    rating: float | None
    reviews: int | None


class Anchor(BaseModel):
    name: str
    type: str
    distance_m: float


class Zone(BaseModel):
    zone_id: int
    name: str
    total: float
    best_h3: str
    subscores: dict[str, float | None]
    confidence: float
    drivers: list[str] = Field(max_length=3)
    risks: list[str] = Field(max_length=2)
    gap: dict[str, float]
    gap_flag: bool
    competitors_direct: list[Competitor] = Field(max_length=5)
    competitors_indirect: list[Competitor] = Field(max_length=5)
    anchors: list[Anchor] = Field(max_length=5)
    est_rent_psf_yr: float | None
    rent_confidence: float | None


class RecommendResponse(BaseModel):
    analysis_id: str
    profile: ConceptProfile
    weights: dict[str, float]
    cells: dict  # GeoJSON FeatureCollection
    zones: list[Zone]
    backtest_rho: float | None
```

Create empty `api/__init__.py`.

- [ ] **Step 8: Write `web/lib/types.ts`** (hand mirror; web track owns future edits)

```ts
export type ServiceFormat = "quick_service"|"fast_casual"|"casual_dining"|"fine_dining"|"bar"|"cafe"|"ghost_kitchen";
export type IncomeFit = "low"|"low_to_medium"|"medium"|"medium_to_high"|"high";
export type Catchment = "walk"|"transit"|"drive";
export type Archetype = "students"|"young_adults"|"office_workers"|"families"|"tourists"|"nightlife";
export type SubscoreKey = "D"|"C"|"T"|"A"|"S_spend"|"K"|"Sup";
export const SUBSCORE_KEYS: SubscoreKey[] = ["D","C","T","A","S_spend","K","Sup"];

export interface ConceptProfile {
  concept_name: string; cuisines: string[]; subcuisine: string[]; substitute_cuisines: string[];
  complementary_cuisines: string[]; service_format: ServiceFormat; price_tier: 1|2|3|4; avg_ticket_usd: number;
  dayparts: Partial<Record<"breakfast"|"lunch"|"dinner"|"late_night"|"weekend", number>>;
  customer_archetypes: Archetype[]; target_age_mix: Record<string, number>;
  dine_in_importance: number; takeout_importance: number; delivery_importance: number; parking_importance: number;
  pedestrian_importance: number; transit_importance: number; nightlife_importance: number; office_importance: number;
  university_importance: number; family_importance: number; visibility_importance: number;
  income_fit: IncomeFit; catchment: Catchment; catchment_tau_min: number; footprint_sqft: [number, number]; seats: number;
  supplier_types: string[]; direct_competitor_description: string; is_franchise: boolean;
  proposed_weights: Partial<Record<SubscoreKey, number>>; confidence: number; clarifying_questions: string[];
}
export interface Competitor { id: string; name: string; distance_m: number; similarity: number; rating: number|null; reviews: number|null; }
export interface Anchor { name: string; type: string; distance_m: number; }
export interface Zone {
  zone_id: number; name: string; total: number; best_h3: string; subscores: Record<SubscoreKey, number|null>;
  confidence: number; drivers: string[]; risks: string[]; gap: { demand: number; supply: number; gap: number };
  gap_flag: boolean; competitors_direct: Competitor[]; competitors_indirect: Competitor[]; anchors: Anchor[];
  est_rent_psf_yr: number|null; rent_confidence: number|null;
}
export interface CellProps extends Record<SubscoreKey, number|null> { h3: string; total: number; confidence: number; zone_id: number|null; }
export interface RecommendResponse {
  analysis_id: string; profile: ConceptProfile; weights: Record<SubscoreKey, number>;
  cells: GeoJSON.FeatureCollection<GeoJSON.Polygon, CellProps>; zones: Zone[]; backtest_rho: number|null;
}
```

- [ ] **Step 9: Run tests, commit**

Run: `.venv/bin/python -m pytest -q` → all pass.
```bash
git add -A && git commit -m "feat: freeze contracts (ConceptProfile, RecommendResponse, cell_features, places) with py/ts mirrors" && git push
```

---

### Task 3: Shared `brain/` team files and `.claude/agents`

**Files:**
- Create: `brain/team.md`, `brain/demo.md`, `.claude/agents/data-ingest.md`, `.claude/agents/backend.md`, `.claude/agents/frontend.md`, `.claude/agents/qa.md`
- Modify: `brain/plan.md`, `brain/architecture.md`, `brain/tasks.md`, `brain/progress.md`

**Interfaces:**
- Produces: the files every developer's Claude session reads at start.

- [ ] **Step 1: Write `brain/team.md`**

```markdown
# Forkcast — Team

## Ownership

| Track | Owner | Folders | Branch prefix |
|---|---|---|---|
| Foundation / data | Dev 1 (cylee) + Claude | `ingest/`, `contracts/`, `data/`, `brain/`, `.claude/`, `docker/` | `data/*` |
| Backend | Dev 2 | `api/`, `tests/test_api*.py`, `tests/test_scoring*.py` | `api/*` |
| Web | Dev 3 | `web/` | `web/*` |

## Rules
- Commit after every task. Rebase on `main` before merging. Never force-push `main`.
- `contracts/` is frozen after the foundation phase. To change it: edit, add a row to the change log below, tell the team.
- Update only your own section of `brain/progress.md`.

## Hour-10 checkpoint
- [ ] All three on `main`, `docker compose up`, Korean street-food concept runs end-to-end.
- [ ] `contracts/` frozen.

## Blockers
| Date | Who | Blocker | Status |
|---|---|---|---|

## Contract change log
| Date | Who | File | Change |
|---|---|---|---|
```

- [ ] **Step 2: Write `brain/demo.md`**

```markdown
# Forkcast — Demo Script (3 min)

## Pre-demo checklist
- [ ] `docker compose up` clean; `GET /api/meta` returns backtest ρ and N.
- [ ] Three example chips parse from cache (no live LLM dependency for parse).
- [ ] Explain endpoint responds < 4 s on zone #1 of each example.
- [ ] Reverse-mode pin location chosen and tested.
- [ ] Browser zoom 110%, map centered on Oakland, 3 mi radius.

## Script
1. "Cheap Korean street food under $15 for college students, open late." Pin Oakland, 3 mi. Show heatmap. Click #1: student fit, late-night traffic, zero direct Korean competitors, White-Space bars.
2. Refine: "Turn this into premium Korean BBQ, $50/person, groups, parking." Map moves toward Shadyside / Downtown / suburban strips. Point at Cost and Parking sub-scores.
3. "Family steak & seafood, big dining room, parking, weekend dinners." Map shifts to suburban retail corridors.
4. Toggle Competition and Rent layers. Flip to reverse mode on a vacant storefront → top concepts.
5. Footer: "Backtested against N open Pittsburgh restaurants, ρ = 0.xx." One-line disclaimer.
```

- [ ] **Step 3: Write `.claude/agents/*.md`** (four files, same shape; frontmatter `name`, `description`, then role text)

`.claude/agents/data-ingest.md`:
```markdown
---
name: data-ingest
description: Owns ingest/ scripts, data/ layout, cell_features construction. Use for any Census, LODES, WPRDC, OSM, GTFS, Google Places, BestTime, Voyage, rent, or affinity work.
---
You own `ingest/` and `data/`. Read `contracts/cell_features.md` before touching columns. Every script is idempotent and accepts `--limit N`. Cache raw API responses under `data/raw/<source>/`. Never call Google per hex. Never ingest ACS ancestry or foreign-born tables. Write parquet to `data/processed/` and upsert the DB via `ingest/common.py`. Run `make test` before committing.
```

`.claude/agents/backend.md`:
```markdown
---
name: backend
description: Owns api/ — FastAPI routers, scoring engine, concept parser, refine, explainer, zones, reverse mode, backtest. Use for any scoring or API work.
---
You own `api/` and its tests. Scoring is deterministic NumPy over in-memory `cell_features` and `places`; the LLM never ranks. Validate LLM weights (0–1, clamp ≤ 0.4, renormalize) and store final weights in `analyses.weights_json`. Explainer prompts receive computed numbers only. Every endpoint output must validate against `contracts/`. Run `make test` before committing.
```

`.claude/agents/frontend.md`:
```markdown
---
name: frontend
description: Owns web/ — Next.js 14, MapLibre hex map, layer toggles, leaderboard, chips, refine bar, Why-Here, reverse mode UI.
---
You own `web/`. Types come from `web/lib/types.ts` (mirror of `contracts/`); do not invent fields. With `NEXT_PUBLIC_USE_FIXTURE=1` the app must run on `data/fixtures/recommend_sample.json` with no backend. Keep one `useAnalysis` hook for state. `tsc --noEmit` and eslint must pass before committing.
```

`.claude/agents/qa.md`:
```markdown
---
name: qa
description: Runs the demo checklist, golden tests, backtest, and integration bug bash. Use before the hour-10 checkpoint and before the demo.
---
You verify, you do not build features. Run `make test`, `make backtest`, and the checklist in `brain/demo.md`. Confirm the three demo concepts rank different #1 zones. Report failures with exact commands and output; hand fixes to the owning track.
```

- [ ] **Step 4: Fill `brain/plan.md`, `brain/architecture.md`, `brain/tasks.md`, `brain/progress.md`**

`brain/plan.md`: copy spec sections 1 (decisions), 6 (team workflow) and the hour-by-hour build order from `forkcast-proposal.md` §8 with properties removed and reverse mode moved into hours 13–16.

`brain/architecture.md`: copy the pipeline diagram from proposal §2, the repo layout from the spec §2, the endpoint table from spec §4, and the ownership table.

`brain/tasks.md`:
```markdown
# Forkcast — Tasks

## Phase 0: Planning
- [x] Brainstorm, write spec `docs/superpowers/specs/2026-09-12-forkcast-design.md`
- [x] Write foundation plan `docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`

## Phase 1: Foundation [P1]
- [ ] Task 1 repo skeleton, docker db, schema, CI
- [ ] Task 2 contracts + mirrors
- [ ] Task 3 brain/ team files + agents
- [ ] Task 4 ingest/common.py + 00_grid
- [ ] Task 5 01_census_acs
- [ ] Task 6 02_lodes
- [ ] Task 7 03_wprdc_food + cuisine_taxonomy.yaml
- [ ] Task 8 04_osm_pois (+ GTFS)
- [ ] Task 9 05_google_places
- [ ] Task 10 07_besttime
- [ ] Task 11 08_place_embeddings
- [ ] Task 12 09_spend_capacity
- [ ] Task 13 10_rent_proxy + rents_manual.csv
- [ ] Task 14 11_cuisine_affinity
- [ ] Task 15 12_build_features
- [ ] Task 16 sanity.py + fixtures

## Phase 2: Backend [P2] — plan to be written after foundation
- [ ] scoring modules, weights, zones, parser, refine, explainer, reverse, backtest, endpoints

## Phase 3: Web [P3] — plan to be written after foundation
- [ ] skeleton on fixture, map + layers, leaderboard, chips, refine, Why-Here, reverse UI

## Phase 4: Integration [P1]
- [ ] hour-10 checkpoint, backtest ρ in footer, weight tuning, bug bash, demo rehearsal
```

`brain/progress.md`: add a `## Dev 1 (cylee)` section header and a `## Dev 2` / `## Dev 3` empty header so each developer appends only to their own section.

- [ ] **Step 5: Commit and push**

```bash
git add -A && git commit -m "docs: team ownership, demo script, agent roles, brain plan/architecture/tasks" && git push
```

---

### Task 4: `ingest/common.py` and `00_grid.py`

**Files:**
- Create: `ingest/__init__.py`, `ingest/common.py`, `ingest/00_grid.py`, `tests/test_common.py`, `tests/test_grid.py`, `data/fixtures/raw_sample/county.geojson` (small polygon around Oakland used by tests)

**Interfaces:**
- Produces:
  - `common.ROOT, RAW, PROC, FIXTURES: Path`; `common.H3_RES = 9`; `common.BBOX = (40.18, -80.37, 40.68, -79.68)` (south, west, north, east)
  - `common.engine() -> sqlalchemy.Engine`
  - `common.write_table(df, name, if_exists="replace")`
  - `common.load_cells() -> DataFrame[h3, lat, lng]` (reads `PROC/geo_cells.parquet`)
  - `common.cells_gdf() -> GeoDataFrame[h3, geometry]` (EPSG:4326)
  - `common.area_weight(src_gdf, cells, extensive: list[str], intensive: list[str]) -> DataFrame[h3, *cols]`
  - `common.points_to_h3(df, lat="lat", lng="lng") -> DataFrame` (adds `h3`)
  - `common.disk_sum(series_by_h3, k) -> Series` (sum over `grid_disk(k)`)
  - `common.pct(series) -> Series` (0–100 percentile rank)
  - `common.cli(description) -> argparse.Namespace` with `--limit`
  - `common.save(df, name)` writes `PROC/<name>.parquet` and returns path
- `00_grid.py` produces `PROC/geo_cells.parquet` and DB table `geo_cells`.

- [ ] **Step 1: Write failing tests for common helpers**

`tests/test_common.py`:
```python
import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from ingest import common


def test_pct_ranks_0_to_100():
    s = pd.Series([10, 20, 30, 40])
    p = common.pct(s)
    assert p.min() >= 0 and p.max() <= 100
    assert p.iloc[-1] > p.iloc[0]


def test_points_to_h3_adds_res9_cell():
    df = pd.DataFrame({"lat": [40.4406], "lng": [-79.9959]})
    out = common.points_to_h3(df)
    assert out["h3"].str.len().eq(15).all()


def test_disk_sum_includes_neighbors():
    import h3
    c = h3.latlng_to_cell(40.4406, -79.9959, 9)
    n = h3.grid_disk(c, 1)[1]
    s = pd.Series({c: 1.0, n: 2.0})
    out = common.disk_sum(s, 1)
    assert out[c] == 3.0


def test_area_weight_splits_extensive_and_averages_intensive():
    src = gpd.GeoDataFrame({"pop": [100.0], "inc": [50.0]}, geometry=[box(0, 0, 2, 1)], crs="EPSG:4326")
    cells = gpd.GeoDataFrame({"h3": ["a", "b"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:4326")
    out = common.area_weight(src, cells, extensive=["pop"], intensive=["inc"]).set_index("h3")
    assert abs(out.loc["a", "pop"] - 50) < 1e-6
    assert abs(out.loc["b", "inc"] - 50) < 1e-6
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_common.py -q` → FAIL `ModuleNotFoundError: ingest.common`.

- [ ] **Step 3: Write `ingest/common.py`** (and empty `ingest/__init__.py`)

```python
import argparse
import os
import pathlib

import geopandas as gpd
import h3
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import Polygon
from sqlalchemy import create_engine

load_dotenv()

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
PROC = ROOT / "data/processed"
FIXTURES = ROOT / "data/fixtures"
H3_RES = 9
BBOX = (40.18, -80.37, 40.68, -79.68)  # south, west, north, east
STATE_FIPS, COUNTY_FIPS = "42", "003"
EQUAL_AREA = "EPSG:6565"  # NAD83(2011) Pennsylvania South, meters


def engine():
    return create_engine(os.environ.get("DATABASE_URL",
                                        "postgresql+psycopg://forkcast:forkcast@localhost:5432/forkcast"))


def write_table(df: pd.DataFrame, name: str, if_exists: str = "replace") -> None:
    df.to_sql(name, engine(), if_exists=if_exists, index=False, method="multi", chunksize=2000)


def save(df: pd.DataFrame, name: str) -> pathlib.Path:
    PROC.mkdir(parents=True, exist_ok=True)
    path = PROC / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(PROC / f"{name}.parquet")


def load_cells() -> pd.DataFrame:
    return load("geo_cells")[["h3", "lat", "lng"]]


def cell_polygon(h: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h)])


def cells_gdf() -> gpd.GeoDataFrame:
    cells = load_cells()
    return gpd.GeoDataFrame(cells[["h3"]], geometry=[cell_polygon(h) for h in cells["h3"]], crs="EPSG:4326")


def area_weight(src: gpd.GeoDataFrame, cells: gpd.GeoDataFrame,
                extensive: list[str], intensive: list[str]) -> pd.DataFrame:
    """Extensive columns (counts) are split by area share of the source polygon.
    Intensive columns (rates, medians) are averaged weighted by intersection area."""
    s = src.to_crs(EQUAL_AREA).copy()
    s["_src_area"] = s.geometry.area
    s["_sid"] = range(len(s))
    c = cells.to_crs(EQUAL_AREA)[["h3", "geometry"]]
    inter = gpd.overlay(s, c, how="intersection", keep_geom_type=False)
    inter["_ia"] = inter.geometry.area
    out = pd.DataFrame({"h3": inter["h3"]})
    for col in extensive:
        out[col] = inter[col] * inter["_ia"] / inter["_src_area"]
    for col in intensive:
        out[col] = inter[col] * inter["_ia"]
    out["_ia"] = inter["_ia"]
    g = out.groupby("h3")
    res = g[extensive].sum() if extensive else pd.DataFrame(index=g.size().index)
    for col in intensive:
        res[col] = g[col].sum() / g["_ia"].sum()
    return res.reset_index()


def points_to_h3(df: pd.DataFrame, lat: str = "lat", lng: str = "lng") -> pd.DataFrame:
    df = df.copy()
    df["h3"] = [h3.latlng_to_cell(a, b, H3_RES) for a, b in zip(df[lat], df[lng])]
    return df


def disk_sum(s: pd.Series, k: int) -> pd.Series:
    """s indexed by h3. Returns, for every index cell, the sum over grid_disk(k)."""
    d = s.to_dict()
    return pd.Series({h: sum(d.get(n, 0.0) for n in h3.grid_disk(h, k)) for h in s.index})


def pct(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def cli(description: str) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--limit", type=int, default=None, help="process only N rows (smoke run)")
    p.add_argument("--no-db", action="store_true", help="write parquet only")
    return p.parse_args()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_common.py -q` → PASS (4 tests).

- [ ] **Step 5: Write failing grid test**

`data/fixtures/raw_sample/county.geojson`: a GeoJSON `Polygon` roughly around Oakland, coordinates `[[-80.00,40.43],[-79.94,40.43],[-79.94,40.46],[-80.00,40.46],[-80.00,40.43]]`.

`tests/test_grid.py`:
```python
import geopandas as gpd

from ingest import common
from tests.conftest import load_script


def test_grid_from_polygon_yields_res9_cells():
    grid = load_script("00_grid")
    poly = gpd.read_file(common.FIXTURES / "raw_sample/county.geojson").geometry.iloc[0]
    df = grid.build_grid(poly)
    assert {"h3", "lat", "lng", "wkt"} <= set(df.columns)
    assert 100 < len(df) < 1000
    assert df["h3"].is_unique
```

- [ ] **Step 6: Run to verify failure** → `FileNotFoundError` for `00_grid.py`.

- [ ] **Step 7: Write `ingest/00_grid.py`**

```python
"""H3 res-9 grid for Allegheny County → data/processed/geo_cells.parquet + geo_cells table."""
import io
import zipfile

import geopandas as gpd
import h3
import pandas as pd
import requests
from sqlalchemy import text

from ingest import common

COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"


def county_polygon():
    path = common.RAW / "tiger/cb_2023_us_county_500k.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(COUNTY_URL, timeout=120).content)
    gdf = gpd.read_file(f"zip://{path}")
    row = gdf[(gdf.STATEFP == common.STATE_FIPS) & (gdf.COUNTYFP == common.COUNTY_FIPS)]
    return row.geometry.iloc[0]


def build_grid(poly) -> pd.DataFrame:
    cells = sorted(h3.geo_to_cells(poly, common.H3_RES))
    rows = []
    for c in cells:
        lat, lng = h3.cell_to_latlng(c)
        rows.append({"h3": c, "lat": lat, "lng": lng, "wkt": common.cell_polygon(c).wkt})
    return pd.DataFrame(rows)


def main():
    args = common.cli(__doc__)
    df = build_grid(county_polygon())
    if args.limit:
        df = df.head(args.limit)
    common.save(df, "geo_cells")
    if not args.no_db:
        eng = common.engine()
        with eng.begin() as con:
            con.execute(text("DELETE FROM geo_cells"))
        common.write_table(df.rename(columns={"wkt": "geom"}), "geo_cells_stage")
        with eng.begin() as con:
            con.execute(text("""INSERT INTO geo_cells (h3, lat, lng, geom)
                                SELECT h3, lat, lng, ST_GeomFromText(geom, 4326) FROM geo_cells_stage"""))
            con.execute(text("DROP TABLE geo_cells_stage"))
    print(f"geo_cells: {len(df)} cells")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run tests and the real script**

Run: `.venv/bin/python -m pytest tests/test_grid.py -q` → PASS.
Run: `make ingest STEP=00` → prints roughly `geo_cells: 7xxx cells`. Verify: `docker compose exec db psql -U forkcast -c "select count(*) from geo_cells"`.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(ingest): common helpers and H3 res-9 county grid" && git push
```

---

### Task 5: `01_census_acs.py`

**Files:**
- Create: `ingest/01_census_acs.py`, `tests/test_acs.py`

**Interfaces:**
- Consumes: `common.area_weight`, `common.cells_gdf`.
- Produces: `PROC/acs.parquet` with columns `h3, pop_total, hh_count, median_hh_income, income_lt25k, income_25_50k, income_50_75k, income_75_100k, income_100_150k, income_150k_plus, pct_age_18_24, pct_age_25_34, pct_age_35_54, pct_age_55p, pct_families_with_kids, avg_hh_size, pct_no_vehicle, pct_renters, pct_bachelors_plus, pct_students`. Function `derive(df_raw) -> DataFrame` (block-group level, pure).

- [ ] **Step 1: Write failing test for `derive`**

`tests/test_acs.py`:
```python
import pandas as pd

from tests.conftest import load_script


def test_derive_computes_shares():
    acs = load_script("01_census_acs")
    raw = pd.DataFrame([{
        "GEOID": "420030001001", "B01003_001E": 1000, "B11001_001E": 400, "B19013_001E": 50000,
        **{v: 0 for v in acs.VARS if v not in ("B01003_001E", "B11001_001E", "B19013_001E")},
    }])
    raw["B19001_001E"] = 400; raw["B19001_002E"] = 100  # <10k → lt25k bucket
    raw["B25003_001E"] = 400; raw["B25003_003E"] = 300
    raw["B01001_001E"] = 1000; raw["B01001_007E"] = 100  # male 18-19
    out = acs.derive(raw).iloc[0]
    assert out["pop_total"] == 1000
    assert abs(out["income_lt25k"] - 0.25) < 1e-9
    assert abs(out["pct_renters"] - 0.75) < 1e-9
    assert abs(out["pct_age_18_24"] - 0.10) < 1e-9
```

- [ ] **Step 2: Run to verify failure** → FileNotFoundError.

- [ ] **Step 3: Write `ingest/01_census_acs.py`**

```python
"""ACS 5-yr 2023 block groups → cell demographics. No ancestry / foreign-born tables."""
import io
import json
import os
import zipfile

import geopandas as gpd
import pandas as pd
import requests

from ingest import common

YEAR = 2023
BG_SHP_URL = f"https://www2.census.gov/geo/tiger/TIGER{YEAR}/BG/tl_{YEAR}_42_bg.zip"

AGE_M = {"18_24": ["007", "008", "009", "010"], "25_34": ["011", "012"],
         "35_54": ["013", "014", "015", "016"], "55p": [f"{i:03d}" for i in range(17, 26)]}
AGE_F = {k: [f"{int(v) + 24:03d}" for v in vs] for k, vs in AGE_M.items()}
INCOME = {"income_lt25k": ["002", "003", "004", "005"], "income_25_50k": ["006", "007", "008", "009", "010"],
          "income_50_75k": ["011", "012"], "income_75_100k": ["013"],
          "income_100_150k": ["014", "015"], "income_150k_plus": ["016", "017"]}

VARS = ["B01003_001E", "B11001_001E", "B19013_001E", "B19001_001E", "B01001_001E",
        "B11005_001E", "B11005_002E", "B25010_001E", "B25044_001E", "B25044_003E", "B25044_010E",
        "B25003_001E", "B25003_003E", "B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E",
        "B14007_001E", "B14007_017E", "B14007_018E"]
VARS += [f"B19001_{s}E" for ss in INCOME.values() for s in ss]
VARS += [f"B01001_{s}E" for ss in list(AGE_M.values()) + list(AGE_F.values()) for s in ss]


def fetch() -> pd.DataFrame:
    path = common.RAW / "acs/bg_2023.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = (f"https://api.census.gov/data/{YEAR}/acs/acs5?get={','.join(VARS)}"
               f"&for=block%20group:*&in=state:{common.STATE_FIPS}%20county:{common.COUNTY_FIPS}"
               f"&key={os.environ['CENSUS_API_KEY']}")
        path.write_text(json.dumps(requests.get(url, timeout=120).json()))
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    for v in VARS:
        df[v] = pd.to_numeric(df[v], errors="coerce").clip(lower=0)
    return df


def _share(df, num_cols, den_col):
    den = df[den_col].replace(0, pd.NA)
    return (df[num_cols].sum(axis=1) / den).fillna(0).astype(float)


def derive(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"GEOID": df["GEOID"]})
    out["pop_total"] = df["B01003_001E"]
    out["hh_count"] = df["B11001_001E"]
    out["median_hh_income"] = df["B19013_001E"]
    for k, ss in INCOME.items():
        out[k] = _share(df, [f"B19001_{s}E" for s in ss], "B19001_001E")
    for k in AGE_M:
        cols = [f"B01001_{s}E" for s in AGE_M[k] + AGE_F[k]]
        out[f"pct_age_{k}"] = _share(df, cols, "B01001_001E")
    out["pct_families_with_kids"] = _share(df, ["B11005_002E"], "B11005_001E")
    out["avg_hh_size"] = df["B25010_001E"]
    out["pct_no_vehicle"] = _share(df, ["B25044_003E", "B25044_010E"], "B25044_001E")
    out["pct_renters"] = _share(df, ["B25003_003E"], "B25003_001E")
    out["pct_bachelors_plus"] = _share(df, ["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"], "B15003_001E")
    out["pct_students"] = _share(df, ["B14007_017E", "B14007_018E"], "B14007_001E")
    return out


def block_groups() -> gpd.GeoDataFrame:
    path = common.RAW / "tiger/tl_2023_42_bg.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(BG_SHP_URL, timeout=300).content)
    gdf = gpd.read_file(f"zip://{path}")
    return gdf[gdf.COUNTYFP == common.COUNTY_FIPS][["GEOID", "geometry"]]


EXTENSIVE = ["pop_total", "hh_count"]


def main():
    args = common.cli(__doc__)
    bg = derive(fetch())
    if args.limit:
        bg = bg.head(args.limit)
    gdf = block_groups().merge(bg, on="GEOID")
    intensive = [c for c in bg.columns if c not in EXTENSIVE + ["GEOID"]]
    cells = common.area_weight(gdf, common.cells_gdf(), extensive=EXTENSIVE, intensive=intensive)
    common.save(cells, "acs")
    print(f"acs: {len(cells)} cells, pop sum {cells.pop_total.sum():,.0f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests and script**

Run: `.venv/bin/python -m pytest tests/test_acs.py -q` → PASS.
Run: `make ingest STEP=01` → pop sum should be about 1.2 M (Allegheny County population).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ingest): ACS block-group demographics area-weighted to cells" && git push
```

---

### Task 6: `02_lodes.py`

**Files:**
- Create: `ingest/02_lodes.py`, `tests/test_lodes.py`

**Interfaces:**
- Produces: `PROC/lodes.parquet` with `h3, workers_daytime, workers_high_wage`. Function `to_block_groups(df) -> DataFrame[GEOID, workers_daytime, workers_high_wage]`.

- [ ] **Step 1: Write failing test**

`tests/test_lodes.py`:
```python
import pandas as pd

from tests.conftest import load_script


def test_to_block_groups_rolls_up_blocks():
    lodes = load_script("02_lodes")
    raw = pd.DataFrame({"w_geocode": ["420030001001001", "420030001001002", "420030002001001"],
                        "C000": [10, 5, 7], "CE03": [4, 1, 2]})
    out = lodes.to_block_groups(raw).set_index("GEOID")
    assert out.loc["420030001001", "workers_daytime"] == 15
    assert out.loc["420030001001", "workers_high_wage"] == 5
    assert len(out) == 2
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/02_lodes.py`**

```python
"""LODES WAC 2021 (PA) → daytime workers per cell."""
import importlib.util

import pandas as pd
import requests

from ingest import common

URL = "https://lehd.ces.census.gov/data/lodes/LODES8/pa/wac/pa_wac_S000_JT00_2021.csv.gz"


def fetch() -> pd.DataFrame:
    path = common.RAW / "lodes/pa_wac_S000_JT00_2021.csv.gz"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(URL, timeout=300).content)
    df = pd.read_csv(path, dtype={"w_geocode": str}, usecols=["w_geocode", "C000", "CE03"])
    return df[df.w_geocode.str.startswith(common.STATE_FIPS + common.COUNTY_FIPS)]


def to_block_groups(df: pd.DataFrame) -> pd.DataFrame:
    g = df.assign(GEOID=df.w_geocode.str[:12]).groupby("GEOID")
    return g.agg(workers_daytime=("C000", "sum"), workers_high_wage=("CE03", "sum")).reset_index()


def main():
    args = common.cli(__doc__)
    bg = to_block_groups(fetch())
    if args.limit:
        bg = bg.head(args.limit)
    spec = importlib.util.spec_from_file_location("acs", common.ROOT / "ingest/01_census_acs.py")
    acs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acs)
    gdf = acs.block_groups().merge(bg, on="GEOID")
    cells = common.area_weight(gdf, common.cells_gdf(),
                               extensive=["workers_daytime", "workers_high_wage"], intensive=[])
    common.save(cells, "lodes")
    print(f"lodes: {len(cells)} cells, workers {cells.workers_daytime.sum():,.0f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test and script**

Run: `pytest tests/test_lodes.py -q` → PASS. `make ingest STEP=02` → workers total about 600–700 k.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ingest): LODES daytime workers per cell" && git push
```

---

### Task 7: `03_wprdc_food.py` and `cuisine_taxonomy.yaml`

**Files:**
- Create: `ingest/cuisine_taxonomy.yaml`, `ingest/taxonomy.py`, `ingest/03_wprdc_food.py`, `tests/test_wprdc.py`

**Interfaces:**
- Produces: `PROC/places_wprdc.parquet` with `id, provider, provider_id, name, lat, lng, h3, categories(list), cuisine_key, is_open, source, address`. `taxonomy.load() -> dict`; `taxonomy.cuisine_for(name: str, categories: list[str]) -> str | None`; `taxonomy.is_chain(name) -> bool`.
- `WPRDC_FOOD_RESOURCE_ID` env var: find the "Allegheny County Restaurant/Food Facility" **facilities** resource on https://data.wprdc.org and copy its resource id into `.env` (Step 3).

- [ ] **Step 1: Write `ingest/cuisine_taxonomy.yaml`** (≥ 40 cuisines; excerpt shown, complete the list in the same shape)

```yaml
cuisines:
  korean:      {aliases: [korean, kbbq, bibimbap, bulgogi, tteokbokki], complementary: [japanese, bubble_tea], substitutes: [japanese, chinese], default_price_tier: 2, default_dayparts: {lunch: .3, dinner: .5, late_night: .2}, default_catchment: walk, supplier_types: [asian_grocer, wholesale]}
  japanese:    {aliases: [japanese, sushi, ramen, izakaya], complementary: [korean, bubble_tea], substitutes: [korean, chinese], default_price_tier: 2, default_dayparts: {lunch: .4, dinner: .6}, default_catchment: walk, supplier_types: [asian_grocer, seafood]}
  chinese:     {aliases: [chinese, szechuan, sichuan, cantonese, dim sum, hot pot], complementary: [bubble_tea], substitutes: [korean, thai], default_price_tier: 1, default_dayparts: {lunch: .4, dinner: .6}, default_catchment: transit, supplier_types: [asian_grocer, wholesale]}
  thai:        {aliases: [thai, pad thai], complementary: [vietnamese], substitutes: [vietnamese, chinese], default_price_tier: 2, default_dayparts: {lunch: .4, dinner: .6}, default_catchment: walk, supplier_types: [asian_grocer]}
  vietnamese:  {aliases: [vietnamese, pho, banh mi], complementary: [thai], substitutes: [thai], default_price_tier: 1, default_dayparts: {lunch: .5, dinner: .5}, default_catchment: walk, supplier_types: [asian_grocer]}
  indian:      {aliases: [indian, curry, tandoori, biryani], complementary: [], substitutes: [nepali, pakistani], default_price_tier: 2, default_dayparts: {lunch: .4, dinner: .6}, default_catchment: transit, supplier_types: [wholesale]}
  italian:     {aliases: [italian, pasta, trattoria, osteria], complementary: [wine_bar], substitutes: [pizza, mediterranean], default_price_tier: 3, default_dayparts: {dinner: .8, weekend: .2}, default_catchment: drive, supplier_types: [italian_grocer, wholesale]}
  pizza:       {aliases: [pizza, pizzeria, neapolitan], complementary: [bar], substitutes: [italian], default_price_tier: 1, default_dayparts: {lunch: .3, dinner: .5, late_night: .2}, default_catchment: walk, supplier_types: [italian_grocer, wholesale]}
  mexican:     {aliases: [mexican, taqueria, tacos, burrito], complementary: [bar], substitutes: [tex_mex, latin], default_price_tier: 1, default_dayparts: {lunch: .4, dinner: .4, late_night: .2}, default_catchment: walk, supplier_types: [wholesale, supermarket]}
  american:    {aliases: [american, diner, grill, burgers, burger], complementary: [bar], substitutes: [gastropub, steakhouse], default_price_tier: 2, default_dayparts: {lunch: .4, dinner: .6}, default_catchment: drive, supplier_types: [wholesale]}
  steakhouse:  {aliases: [steakhouse, steak, chophouse], complementary: [wine_bar], substitutes: [american, seafood], default_price_tier: 4, default_dayparts: {dinner: .8, weekend: .2}, default_catchment: drive, supplier_types: [butcher, wholesale]}
  seafood:     {aliases: [seafood, fish, oyster, crab], complementary: [wine_bar], substitutes: [steakhouse], default_price_tier: 3, default_dayparts: {dinner: .8, weekend: .2}, default_catchment: drive, supplier_types: [seafood, wholesale]}
  cafe:        {aliases: [cafe, coffee, espresso, coffeehouse], complementary: [bakery], substitutes: [bakery], default_price_tier: 1, default_dayparts: {breakfast: .5, lunch: .3, afternoon: .2}, default_catchment: walk, supplier_types: [wholesale]}
  bakery:      {aliases: [bakery, patisserie, donut, bagel], complementary: [cafe], substitutes: [cafe], default_price_tier: 1, default_dayparts: {breakfast: .6, lunch: .4}, default_catchment: walk, supplier_types: [wholesale]}
  bar:         {aliases: [bar, pub, tavern, taproom, brewery], complementary: [pizza, american], substitutes: [gastropub, wine_bar], default_price_tier: 2, default_dayparts: {dinner: .3, late_night: .5, weekend: .2}, default_catchment: walk, supplier_types: [wholesale]}
  # … continue to ≥ 40: mediterranean, greek, middle_eastern, turkish, lebanese, ethiopian, caribbean, latin, tex_mex, peruvian, brazilian, french, spanish_tapas, german, polish, soul_food, bbq, southern, fried_chicken, sandwich_deli, salad_healthy, vegan, breakfast_brunch, dessert_ice_cream, bubble_tea, wine_bar, gastropub, nepali, pakistani, filipino, hawaiian_poke, halal, kosher, food_hall
chains:
  - mcdonald's
  - starbucks
  - subway
  - chipotle
  - panera
  - dunkin
  - wendy's
  - burger king
  - taco bell
  - domino's
  - papa john's
  - chick-fil-a
  - five guys
  - primanti          # local chain
  - eat'n park        # local chain
  - sheetz
  - panda express
  - qdoba
  - jimmy john's
```

- [ ] **Step 2: Write `ingest/taxonomy.py` and its failing test**

`tests/test_wprdc.py` (first part):
```python
from ingest import taxonomy


def test_cuisine_for_matches_alias_in_name():
    assert taxonomy.cuisine_for("Seoul Bulgogi House", []) == "korean"


def test_cuisine_for_falls_back_to_categories():
    assert taxonomy.cuisine_for("Joe's", ["thai_restaurant"]) == "thai"


def test_is_chain():
    assert taxonomy.is_chain("Starbucks Coffee")
    assert not taxonomy.is_chain("Blue Sparrow")
```

`ingest/taxonomy.py`:
```python
import functools
import pathlib
import re

import yaml

PATH = pathlib.Path(__file__).with_name("cuisine_taxonomy.yaml")


@functools.lru_cache
def load() -> dict:
    return yaml.safe_load(PATH.read_text())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", " ", s.lower())


def cuisine_for(name: str, categories: list[str]) -> str | None:
    text = _norm(name) + " " + _norm(" ".join(c.replace("_", " ") for c in categories))
    best = None
    for key, spec in load()["cuisines"].items():
        for alias in spec["aliases"]:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                if best is None or len(alias) > len(best[1]):
                    best = (key, alias)
    return best[0] if best else None


def is_chain(name: str) -> bool:
    n = _norm(name)
    return any(c in n for c in load()["chains"])
```

Run: `pytest tests/test_wprdc.py -q` → 3 PASS.

- [ ] **Step 3: Find the WPRDC resource id and set it**

Open https://data.wprdc.org/dataset/allegheny-county-restaurant-food-facility-inspection-violations, choose the **facilities** (not violations) CSV resource, copy the id from its URL (`/resource/<id>`), and put it in `.env` as `WPRDC_FOOD_RESOURCE_ID=`. Confirm with:
```bash
curl -s "https://data.wprdc.org/api/3/action/datastore_search?resource_id=$WPRDC_FOOD_RESOURCE_ID&limit=1" | head -c 800
```
Record the exact column names for facility id, name, status, description, latitude, longitude, address in `ingest/03_wprdc_food.py` `COLS` (Step 4) if they differ from the defaults there.

- [ ] **Step 4: Write failing test for the row normalizer, then the script**

Append to `tests/test_wprdc.py`:
```python
def test_normalize_rows_marks_open_and_geocodes():
    w = load_script("03_wprdc_food")
    rows = [{"id": "1", "facility_name": "Seoul Bulgogi", "status": "1", "description": "Restaurant without Liquor",
             "latitude": "40.44", "longitude": "-79.99", "address": "x"},
            {"id": "2", "facility_name": "Closed Diner", "status": "0", "description": "Restaurant",
             "latitude": "40.44", "longitude": "-79.99", "address": "y"},
            {"id": "3", "facility_name": "No Geo", "status": "1", "description": "Restaurant",
             "latitude": "", "longitude": "", "address": "z"}]
    df = w.normalize_rows(rows)
    assert len(df) == 2
    assert df.loc[df.provider_id == "1", "is_open"].item() is True
    assert df.loc[df.provider_id == "2", "is_open"].item() is False
    assert df.loc[df.provider_id == "1", "cuisine_key"].item() == "korean"
```
(add `from tests.conftest import load_script` at top.)

`ingest/03_wprdc_food.py`:
```python
"""WPRDC Allegheny County food facilities → authoritative restaurant list with open/closed status."""
import json
import os

import pandas as pd
import requests

from ingest import common, taxonomy

API = "https://data.wprdc.org/api/3/action/datastore_search"
COLS = {"id": "id", "name": "facility_name", "status": "status", "desc": "description",
        "lat": "latitude", "lng": "longitude", "address": "address"}
KEEP_TYPES = ("restaurant", "bar", "tavern", "cafe", "coffee", "bakery", "pizza", "deli", "food truck", "brewery")


def fetch() -> list[dict]:
    path = common.RAW / "wprdc/food_facilities.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    rid, offset, rows = os.environ["WPRDC_FOOD_RESOURCE_ID"], 0, []
    while True:
        r = requests.get(API, params={"resource_id": rid, "limit": 5000, "offset": offset}, timeout=60).json()
        recs = r["result"]["records"]
        rows += recs
        if len(recs) < 5000:
            break
        offset += 5000
    path.write_text(json.dumps(rows))
    return rows


def normalize_rows(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).rename(columns={v: k for k, v in COLS.items()})
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    df = df.dropna(subset=["lat", "lng"])
    df = df[df["desc"].str.lower().str.contains("|".join(KEEP_TYPES), na=False)]
    df["is_open"] = df["status"].astype(str).isin(["1", "1.0", "open", "Open", "True", "true"])
    df["provider_id"] = df["id"].astype(str)
    df["id"] = "wprdc:" + df["provider_id"]
    df["provider"] = "wprdc"
    df["source"] = "wprdc"
    df["categories"] = df["desc"].apply(lambda d: [str(d).lower()])
    df["cuisine_key"] = [taxonomy.cuisine_for(n, c) for n, c in zip(df["name"], df["categories"])]
    df = common.points_to_h3(df)
    return df[["id", "provider", "provider_id", "name", "lat", "lng", "h3", "categories",
               "cuisine_key", "is_open", "source", "address"]].reset_index(drop=True)


def main():
    args = common.cli(__doc__)
    df = normalize_rows(fetch())
    if args.limit:
        df = df.head(args.limit)
    common.save(df, "places_wprdc")
    print(f"wprdc: {len(df)} facilities, {df.is_open.sum()} open")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests and script**

Run: `pytest tests/test_wprdc.py -q` → PASS. `make ingest STEP=03` → several thousand facilities, majority open.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(ingest): WPRDC food facilities and cuisine taxonomy" && git push
```

---

### Task 8: `04_osm_pois.py` (Overpass) + GTFS

**Files:**
- Create: `ingest/04_osm_pois.py`, `tests/test_osm.py`

**Interfaces:**
- Produces:
  - `PROC/osm_pois.parquet`: `osm_id, name, kind, lat, lng, h3` where `kind` ∈ anchor types (`university, school, office, hospital, hotel, bar, nightclub, mall, cinema, stadium, park, attraction, transit_station, parking, shop, amenity_other`) or supplier types (`wholesale, supermarket, seafood, butcher, greengrocer, asian_grocer, italian_grocer`).
  - `PROC/osm_cells.parquet`: `h3, anchor_<type>…, dist_to_university_km, dist_to_hospital_km, dist_to_transit_station_km, dist_to_stadium_km, parking_lots, walkable_poi_density, poi_density, main_road_frontage, transit_daily_trips, dist_to_<supplier>_km…`
  - Functions: `classify(tags: dict) -> str | None`, `cell_metrics(pois: DataFrame, cells: DataFrame, roads_h3: set, gtfs_trips: Series) -> DataFrame`.

- [ ] **Step 1: Write failing tests**

`tests/test_osm.py`:
```python
import pandas as pd

from tests.conftest import load_script


def test_classify_tags():
    osm = load_script("04_osm_pois")
    assert osm.classify({"amenity": "university"}) == "university"
    assert osm.classify({"shop": "supermarket"}) == "supermarket"
    assert osm.classify({"shop": "supermarket", "cuisine": "asian"}) == "asian_grocer"
    assert osm.classify({"amenity": "parking"}) == "parking"
    assert osm.classify({"railway": "station"}) == "transit_station"
    assert osm.classify({"foo": "bar"}) is None


def test_cell_metrics_counts_and_distances():
    import h3
    osm = load_script("04_osm_pois")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    lat, lng = h3.cell_to_latlng(c)
    cells = pd.DataFrame({"h3": [c], "lat": [lat], "lng": [lng]})
    pois = pd.DataFrame({"osm_id": [1, 2], "name": ["Pitt", "Giant Eagle"], "kind": ["university", "supermarket"],
                         "lat": [lat, lat + 0.01], "lng": [lng, lng], "h3": [c, h3.latlng_to_cell(lat + 0.01, lng, 9)]})
    out = osm.cell_metrics(pois, cells, roads_h3={c}, gtfs_trips=pd.Series({c: 120.0})).set_index("h3")
    assert out.loc[c, "anchor_university"] == 1
    assert 0.9 < out.loc[c, "dist_to_supermarket_km"] < 1.3
    assert out.loc[c, "main_road_frontage"] == 1
    assert out.loc[c, "transit_daily_trips"] == 120.0
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/04_osm_pois.py`**

```python
"""OSM (Overpass) anchors, parking, shops, suppliers, main roads + PRT GTFS trips → per-cell access features."""
import io
import json
import math
import zipfile

import h3
import numpy as np
import pandas as pd
import requests

from ingest import common

OVERPASS = "https://overpass-api.de/api/interpreter"
GTFS_URL = "https://www.rideprt.org/siteassets/developer-resources/gtfs/general_transit.zip"  # verify on rideprt.org developer page
S, W, N, E = common.BBOX
BB = f"({S},{W},{N},{E})"

ANCHORS = ["university", "school", "office", "hospital", "hotel", "bar", "nightclub", "mall", "cinema",
           "stadium", "park", "attraction", "transit_station"]
SUPPLIERS = ["wholesale", "supermarket", "seafood", "butcher", "greengrocer", "asian_grocer", "italian_grocer"]
DIST_ANCHORS = ["university", "hospital", "transit_station", "stadium"]

QUERIES = {
    "pois": f"""[out:json][timeout:180];(
      nwr["amenity"~"^(university|college|school|hospital|bar|pub|nightclub|cinema|theatre|parking|cafe|restaurant|fast_food|marketplace)$"]{BB};
      nwr["tourism"~"^(hotel|attraction|museum|zoo)$"]{BB};
      nwr["leisure"~"^(park|stadium|sports_centre)$"]{BB};
      nwr["shop"]{BB};
      nwr["office"]{BB};
      nwr["railway"="station"]{BB};
      nwr["public_transport"="station"]{BB};
    );out center tags;""",
    "roads": f"""[out:json][timeout:180];(way["highway"~"^(primary|secondary|tertiary)$"]{BB};);out geom;""",
}


def overpass(name: str) -> dict:
    path = common.RAW / f"osm/{name}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.post(OVERPASS, data={"data": QUERIES[name]}, timeout=300)
        r.raise_for_status()
        path.write_text(r.text)
    return json.loads(path.read_text())


def classify(t: dict) -> str | None:
    a, s, shop = t.get("amenity"), t.get("shop"), t.get("shop")
    if a in ("university", "college"):
        return "university"
    if a == "school":
        return "school"
    if a == "hospital":
        return "hospital"
    if a in ("bar", "pub"):
        return "bar"
    if a == "nightclub":
        return "nightclub"
    if a in ("cinema", "theatre"):
        return "cinema"
    if a == "parking":
        return "parking"
    if t.get("tourism") == "hotel":
        return "hotel"
    if t.get("tourism") in ("attraction", "museum", "zoo"):
        return "attraction"
    if t.get("leisure") == "park":
        return "park"
    if t.get("leisure") in ("stadium", "sports_centre"):
        return "stadium"
    if t.get("railway") == "station" or t.get("public_transport") == "station":
        return "transit_station"
    if shop == "mall":
        return "mall"
    if shop == "wholesale":
        return "wholesale"
    if shop == "supermarket":
        cu, nm = (t.get("cuisine") or "").lower(), (t.get("name") or "").lower()
        if any(k in cu or k in nm for k in ("asian", "korean", "chinese", "japanese", "indian", "oriental")):
            return "asian_grocer"
        if "italian" in cu or "italian" in nm:
            return "italian_grocer"
        return "supermarket"
    if shop == "seafood":
        return "seafood"
    if shop == "butcher":
        return "butcher"
    if shop == "greengrocer":
        return "greengrocer"
    if shop:
        return "shop"
    if t.get("office"):
        return "office"
    if a in ("cafe", "restaurant", "fast_food", "marketplace"):
        return "amenity_other"
    return None


def pois_df(data: dict) -> pd.DataFrame:
    rows = []
    for el in data["elements"]:
        t = el.get("tags", {})
        kind = classify(t)
        if not kind:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        rows.append({"osm_id": el["id"], "name": t.get("name", ""), "kind": kind, "lat": lat, "lng": lng})
    return common.points_to_h3(pd.DataFrame(rows))


def roads_h3(data: dict) -> set:
    out = set()
    for el in data["elements"]:
        for p in el.get("geometry", []):
            out.add(h3.latlng_to_cell(p["lat"], p["lon"], common.H3_RES))
    return out


def gtfs_trips_per_cell() -> pd.Series:
    path = common.RAW / "gtfs/prt.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(GTFS_URL, timeout=300).content)
    z = zipfile.ZipFile(path)
    stops = pd.read_csv(z.open("stops.txt"), dtype={"stop_id": str})
    st = pd.read_csv(z.open("stop_times.txt"), dtype={"stop_id": str}, usecols=["stop_id"])
    per_stop = st.groupby("stop_id").size().rename("trips")
    stops = stops.merge(per_stop, left_on="stop_id", right_index=True, how="inner")
    stops = common.points_to_h3(stops, lat="stop_lat", lng="stop_lon")
    return stops.groupby("h3")["trips"].sum() / 7.0  # feed covers a week of service ids; per-day proxy


def _haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _nearest_km(cells: pd.DataFrame, pts: pd.DataFrame) -> np.ndarray:
    if pts.empty:
        return np.full(len(cells), 25.0)
    d = _haversine_km(cells.lat.values[:, None], cells.lng.values[:, None], pts.lat.values[None, :], pts.lng.values[None, :])
    return d.min(axis=1)


def cell_metrics(pois: pd.DataFrame, cells: pd.DataFrame, roads_h3: set, gtfs_trips: pd.Series) -> pd.DataFrame:
    out = cells[["h3"]].copy().set_index("h3")
    counts = pois.groupby(["h3", "kind"]).size().unstack(fill_value=0)
    for k in ANCHORS:
        s = counts[k] if k in counts else pd.Series(0.0, index=counts.index)
        out[f"anchor_{k}"] = common.disk_sum(s.reindex(out.index, fill_value=0.0), 2)
    for k in DIST_ANCHORS:
        out[f"dist_to_{k}_km"] = _nearest_km(cells, pois[pois.kind == k])
    for k in SUPPLIERS:
        out[f"dist_to_{k}_km"] = _nearest_km(cells, pois[pois.kind == k])
    park = counts["parking"] if "parking" in counts else pd.Series(0.0, index=counts.index)
    out["parking_lots"] = common.disk_sum(park.reindex(out.index, fill_value=0.0), 1)
    walk = pois[pois.kind.isin(["shop", "amenity_other", "bar", "cinema", "mall", "attraction"])].groupby("h3").size()
    out["walkable_poi_density"] = common.disk_sum(walk.reindex(out.index, fill_value=0.0), 2)
    out["poi_density"] = pois.groupby("h3").size().reindex(out.index, fill_value=0.0)
    out["main_road_frontage"] = [1.0 if h in roads_h3 else 0.0 for h in out.index]
    out["transit_daily_trips"] = common.disk_sum(gtfs_trips.reindex(out.index, fill_value=0.0), 1)
    return out.reset_index()


def main():
    args = common.cli(__doc__)
    pois = pois_df(overpass("pois"))
    roads = roads_h3(overpass("roads"))
    trips = gtfs_trips_per_cell()
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    common.save(pois, "osm_pois")
    common.save(cell_metrics(pois, cells, roads, trips), "osm_cells")
    sup = pois[pois.kind.isin(SUPPLIERS)].rename(columns={"kind": "supplier_type"})
    sup["id"] = "osm:" + sup.osm_id.astype(str)
    sup["source"] = "osm"
    common.save(sup[["id", "name", "supplier_type", "lat", "lng", "h3", "source"]], "suppliers")
    if not args.no_db:
        common.write_table(common.load("suppliers"), "suppliers")
    print(f"osm: {len(pois)} pois, {pois.kind.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add hand-listed suppliers**

Create `data/suppliers_manual.csv` with header `name,supplier_type,lat,lng` and rows for Restaurant Depot (Pittsburgh), Sysco Pittsburgh, US Foods Pittsburgh, Strip District wholesalers (Penn Mac as `italian_grocer`, Lotus Food as `asian_grocer`, Wholey's as `seafood`). Look up coordinates on OpenStreetMap. In `main()`, before saving suppliers, append:
```python
    manual = common.points_to_h3(pd.read_csv(common.ROOT / "data/suppliers_manual.csv"))
    manual["id"] = "manual:" + manual.index.astype(str); manual["source"] = "manual"; manual["osm_id"] = -1
    manual["kind"] = manual["supplier_type"]
    pois = pd.concat([pois, manual[["osm_id", "name", "kind", "lat", "lng", "h3"]]], ignore_index=True)
```
(place this right after `pois = pois_df(...)` so distances include manual suppliers).

- [ ] **Step 5: Run tests and script**

Run: `pytest tests/test_osm.py -q` → PASS. `make ingest STEP=04` (Overpass may take 1–3 min). Expect tens of thousands of POIs.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(ingest): OSM anchors, suppliers, roads, GTFS transit per cell" && git push
```

---

### Task 9: `05_google_places.py`

**Files:**
- Create: `ingest/05_google_places.py`, `tests/test_google.py`

**Interfaces:**
- Produces: `PROC/places.parquet` (merged WPRDC + Google) with columns per `contracts/places.md` minus `embedding`, plus `PROC/google_raw.parquet`. Functions: `search_cells() -> list[str]` (res-8 cells covering the county), `parse_place(p: dict) -> dict`, `match(wprdc: DataFrame, google: DataFrame) -> DataFrame` (name + distance ≤ 150 m).

- [ ] **Step 1: Write failing tests**

`tests/test_google.py`:
```python
import pandas as pd

from tests.conftest import load_script


def test_parse_place_maps_fields():
    g = load_script("05_google_places")
    p = {"id": "abc", "displayName": {"text": "Seoul Bulgogi"}, "location": {"latitude": 40.44, "longitude": -79.99},
         "rating": 4.5, "userRatingCount": 120, "priceLevel": "PRICE_LEVEL_MODERATE",
         "businessStatus": "OPERATIONAL", "types": ["korean_restaurant", "restaurant"],
         "editorialSummary": {"text": "Casual Korean spot."}}
    r = g.parse_place(p)
    assert r["price_level"] == 2 and r["reviews"] == 120 and r["google_open"] is True
    assert r["cuisine_key"] == "korean"


def test_match_by_name_and_distance():
    g = load_script("05_google_places")
    w = pd.DataFrame({"id": ["wprdc:1"], "name": ["Seoul Bulgogi House"], "lat": [40.4400], "lng": [-79.9900],
                      "is_open": [True], "provider_id": ["1"], "cuisine_key": ["korean"], "categories": [["restaurant"]],
                      "h3": ["x"], "provider": ["wprdc"], "source": ["wprdc"], "address": ["a"]})
    gg = pd.DataFrame([g.parse_place({"id": "abc", "displayName": {"text": "Seoul Bulgogi"},
                                      "location": {"latitude": 40.4405, "longitude": -79.9902},
                                      "rating": 4.5, "userRatingCount": 120, "priceLevel": "PRICE_LEVEL_MODERATE",
                                      "businessStatus": "OPERATIONAL", "types": ["restaurant"]})])
    out = g.match(w, gg)
    assert out.loc[out.id == "wprdc:1", "rating"].item() == 4.5
    assert out.loc[out.id == "wprdc:1", "source"].item() == "wprdc+google"
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/05_google_places.py`**

```python
"""Google Places (New) Nearby Search, county-wide on a res-8 grid, field-masked, cached. Merged onto WPRDC rows."""
import json
import os
import re

import h3
import numpy as np
import pandas as pd
import requests

from ingest import common, taxonomy

URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = ("places.id,places.displayName,places.location,places.rating,places.userRatingCount,"
          "places.priceLevel,places.businessStatus,places.types,places.editorialSummary")
TYPES = ["restaurant", "cafe", "bar", "bakery", "meal_takeaway"]
PRICE = {"PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2, "PRICE_LEVEL_EXPENSIVE": 3,
         "PRICE_LEVEL_VERY_EXPENSIVE": 4}


def search_cells() -> list[str]:
    cells = common.load_cells()
    return sorted({h3.cell_to_parent(c, 8) for c in cells.h3})


def _query(lat, lng, radius_m, page_token=None) -> dict:
    body = {"includedTypes": TYPES, "maxResultCount": 20,
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}}}
    r = requests.post(URL, json=body, timeout=30,
                      headers={"X-Goog-Api-Key": os.environ["GOOGLE_PLACES_API_KEY"], "X-Goog-FieldMask": FIELDS})
    r.raise_for_status()
    return r.json()


def fetch_cell(c: str, depth: int = 0) -> list[dict]:
    """Nearby search on the res-8 cell; if 20 results returned (truncated), recurse into res-9 children."""
    path = common.RAW / f"google/{c}.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    lat, lng = h3.cell_to_latlng(c)
    radius = 700 if h3.get_resolution(c) == 8 else 260
    places = _query(lat, lng, radius).get("places", [])
    if len(places) >= 20 and depth < 1:
        places = [p for ch in h3.cell_to_children(c, h3.get_resolution(c) + 1) for p in fetch_cell(ch, depth + 1)]
    path.write_text(json.dumps(places))
    return places


def parse_place(p: dict) -> dict:
    name = p.get("displayName", {}).get("text", "")
    types = p.get("types", [])
    return {"google_id": p["id"], "name": name, "lat": p["location"]["latitude"], "lng": p["location"]["longitude"],
            "rating": p.get("rating"), "reviews": p.get("userRatingCount"),
            "price_level": PRICE.get(p.get("priceLevel")), "google_open": p.get("businessStatus") == "OPERATIONAL",
            "types": types, "summary": (p.get("editorialSummary") or {}).get("text"),
            "cuisine_key": taxonomy.cuisine_for(name, types)}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())[:12]


def match(wprdc: pd.DataFrame, google: pd.DataFrame) -> pd.DataFrame:
    g = google.drop_duplicates("google_id").copy()
    g["_k"] = g.name.map(_norm)
    w = wprdc.copy()
    w["_k"] = w.name.map(_norm)
    m = w.merge(g, on="_k", how="left", suffixes=("", "_g"))
    d = np.hypot((m.lat - m.lat_g) * 111.0, (m.lng - m.lng_g) * 85.0)  # km
    ok = d <= 0.15
    m.loc[~ok, ["google_id", "rating", "reviews", "price_level", "google_open", "types", "summary"]] = None
    m = m.sort_values("reviews", ascending=False).drop_duplicates("id")
    m["source"] = np.where(m.google_id.notna(), "wprdc+google", "wprdc")
    m["is_open"] = m.is_open & m.google_open.fillna(True).astype(bool)
    m["cuisine_key"] = m.cuisine_key.fillna(m.get("cuisine_key_g"))
    m["categories"] = [list(c) + list(t or []) for c, t in zip(m.categories, m.types)]
    m["is_chain"] = m.name.map(taxonomy.is_chain)
    m["provider_id"] = m.provider_id.astype(str)
    # Google-only places (no WPRDC match): keep as their own rows
    extra = g[~g.google_id.isin(m.google_id.dropna())].copy()
    extra["id"] = "google:" + extra.google_id
    extra["provider"], extra["provider_id"], extra["source"] = "google", extra.google_id, "google"
    extra["is_open"] = extra.google_open.astype(bool)
    extra["categories"] = extra.types
    extra["is_chain"] = extra.name.map(taxonomy.is_chain)
    extra["address"] = None
    extra = common.points_to_h3(extra)
    cols = ["id", "provider", "provider_id", "name", "lat", "lng", "h3", "categories", "cuisine_key",
            "price_level", "rating", "reviews", "is_chain", "is_open", "source", "summary"]
    return pd.concat([m[cols], extra[cols]], ignore_index=True)


def main():
    args = common.cli(__doc__)
    cells = search_cells()
    if args.limit:
        cells = cells[: args.limit]
    raw = [parse_place(p) for c in cells for p in fetch_cell(c)]
    google = pd.DataFrame(raw)
    common.save(google, "google_raw")
    places = match(common.load("places_wprdc"), google)
    common.save(places, "places")
    if not args.no_db:
        db = places.copy()
        db["categories"] = db.categories.apply(lambda c: "{" + ",".join(f'"{x}"' for x in c) + "}")
        common.write_table(db, "places_stage")
        from sqlalchemy import text
        with common.engine().begin() as con:
            con.execute(text("DELETE FROM place_activity; DELETE FROM places"))
            con.execute(text("""INSERT INTO places (id, provider, provider_id, name, lat, lng, h3, categories, cuisine_key,
                                price_level, rating, reviews, is_chain, is_open, source, summary)
                                SELECT id, provider, provider_id, name, lat, lng, h3, categories::text[], cuisine_key,
                                price_level, rating, reviews, is_chain, is_open, source, summary FROM places_stage"""))
            con.execute(text("DROP TABLE places_stage"))
    print(f"google: {len(google)} raw, places: {len(places)}, matched {(places.source == 'wprdc+google').sum()}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, then a limited live run, then full**

Run: `pytest tests/test_google.py -q` → PASS.
Run: `make ingest STEP=05 ARGS="--limit 5 --no-db"` → check `data/raw/google/*.json` look right, then `make ingest STEP=05`. Expect ~1,000 res-8 cells → roughly 1,000–2,500 calls (subdivision in dense areas).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ingest): Google Places enrichment merged onto WPRDC places" && git push
```

---

### Task 10: `07_besttime.py` (real traffic for top ~500 POIs + proxy)

**Files:**
- Create: `ingest/07_besttime.py`, `tests/test_besttime.py`

**Interfaces:**
- Produces: `PROC/place_activity.parquet` (`place_id, daypart, busyness`), `PROC/activity_cells.parquet` (`h3, activity_morning, activity_lunch, activity_afternoon, activity_dinner, activity_late_night, activity_weekend, traffic_source`). Functions `dayparts_from_hours(week: list[list[int]]) -> dict[str, float]`, `cells_from_activity(place_activity: DataFrame, places: DataFrame, cells: DataFrame, proxy: DataFrame) -> DataFrame`.

- [ ] **Step 1: Write failing test**

`tests/test_besttime.py`:
```python
from tests.conftest import load_script

DAYPARTS = ["morning", "lunch", "afternoon", "dinner", "late_night", "weekend"]


def test_dayparts_from_hours_buckets_and_scales():
    b = load_script("07_besttime")
    day = [0] * 24
    day[12] = 100  # busy at noon every day
    week = [day] * 7
    out = b.dayparts_from_hours(week)
    assert set(out) == set(DAYPARTS)
    assert out["lunch"] == 100 and out["late_night"] == 0
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/07_besttime.py`**

```python
"""BestTime hourly busyness for top POIs → daypart activity per cell; proxy from anchors/transit/workers elsewhere."""
import json
import os

import h3
import numpy as np
import pandas as pd
import requests

from ingest import common

API = "https://besttime.app/api/v1/forecasts"
TOP_N = 500
HOURS = {"morning": range(6, 11), "lunch": range(11, 14), "afternoon": range(14, 17),
         "dinner": range(17, 21), "late_night": list(range(21, 24)) + list(range(0, 3))}
DAYPARTS = list(HOURS) + ["weekend"]


def fetch_venue(place_id: str, name: str, address: str | None, lat: float, lng: float) -> list[list[int]] | None:
    path = common.RAW / f"besttime/{place_id.replace(':', '_')}.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.post(API, params={"api_key_private": os.environ["BESTTIME_API_KEY_PRIVATE"],
                                   "venue_name": name, "venue_address": address or f"{lat},{lng} Pittsburgh PA"},
                      timeout=60).json()
    week = [d["day_raw"] for d in r.get("analysis", [])] if r.get("status") == "OK" else None
    path.write_text(json.dumps(week))
    return week


def dayparts_from_hours(week: list[list[int]]) -> dict[str, float]:
    arr = np.array(week, dtype=float)  # 7 x 24, Monday first
    out = {k: float(arr[:, list(hrs)].mean()) for k, hrs in HOURS.items()}
    out["weekend"] = float(arr[5:7].mean())
    return out


def proxy_activity(cells: pd.DataFrame, osm: pd.DataFrame, lodes: pd.DataFrame) -> pd.DataFrame:
    df = cells[["h3"]].merge(osm, on="h3", how="left").merge(lodes, on="h3", how="left").fillna(0)
    base = (common.pct(df.walkable_poi_density) + common.pct(df.transit_daily_trips)) / 2
    work = common.pct(df.workers_daytime)
    night = common.pct(df.anchor_bar + df.anchor_nightclub)
    out = pd.DataFrame({"h3": df.h3})
    out["activity_morning"] = 0.5 * base + 0.5 * work
    out["activity_lunch"] = 0.4 * base + 0.6 * work
    out["activity_afternoon"] = 0.6 * base + 0.4 * work
    out["activity_dinner"] = 0.7 * base + 0.3 * night
    out["activity_late_night"] = 0.3 * base + 0.7 * night
    out["activity_weekend"] = 0.6 * base + 0.4 * night
    return out


def cells_from_activity(pa: pd.DataFrame, places: pd.DataFrame, cells: pd.DataFrame, proxy: pd.DataFrame) -> pd.DataFrame:
    """Distance-weighted (grid_disk(2), weight 1/(1+ring)) mean of real venue busyness; proxy where no venue within 2 rings."""
    wide = pa.pivot(index="place_id", columns="daypart", values="busyness")
    wide = wide.merge(places[["id", "h3"]].set_index("id"), left_index=True, right_index=True)
    by_cell = wide.groupby("h3").mean()
    real = {}
    for h in cells.h3:
        num, den = np.zeros(len(DAYPARTS)), 0.0
        for ring, cs in enumerate(h3.grid_ring(h, k) for k in range(3)):
            for c in cs:
                if c in by_cell.index:
                    w = 1.0 / (1 + ring)
                    num += w * by_cell.loc[c, DAYPARTS].values
                    den += w
        if den > 0:
            real[h] = num / den
    out = proxy.set_index("h3").copy()
    out["traffic_source"] = "proxy"
    for h, v in real.items():
        out.loc[h, [f"activity_{d}" for d in DAYPARTS]] = v
        out.loc[h, "traffic_source"] = "real"
    return out.reset_index()


def main():
    args = common.cli(__doc__)
    places = common.load("places")
    top = places[places.is_open & places.reviews.notna()].sort_values("reviews", ascending=False).head(args.limit or TOP_N)
    rows = []
    for _, p in top.iterrows():
        week = fetch_venue(p.id, p.name, p.get("address"), p.lat, p.lng)
        if week and len(week) == 7:
            rows += [{"place_id": p.id, "daypart": d, "busyness": v} for d, v in dayparts_from_hours(week).items()]
    pa = pd.DataFrame(rows, columns=["place_id", "daypart", "busyness"])
    common.save(pa, "place_activity")
    cells = common.load_cells()
    proxy = proxy_activity(cells, common.load("osm_cells"), common.load("lodes"))
    common.save(cells_from_activity(pa, places, cells, proxy), "activity_cells")
    if not args.no_db and len(pa):
        common.write_table(pa, "place_activity", if_exists="append")
    print(f"besttime: {pa.place_id.nunique()} venues with real data")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, smoke, full**

Run: `pytest tests/test_besttime.py -q` → PASS. `make ingest STEP=07 ARGS="--limit 3 --no-db"` then `make ingest STEP=07`. If BestTime key is not available yet, `make ingest STEP=07 ARGS="--limit 0"` still writes the proxy for every cell with `traffic_source = proxy`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ingest): BestTime daypart activity with proxy fallback" && git push
```

---

### Task 11: `08_place_embeddings.py`

**Files:**
- Create: `ingest/08_place_embeddings.py`, `tests/test_embeddings.py`

**Interfaces:**
- Produces: `PROC/place_embeddings.parquet` (`id, embedding: list[float]` 1024) and fills `places.embedding` in DB. Function `embed_text(row) -> str`.

- [ ] **Step 1: Failing test**

`tests/test_embeddings.py`:
```python
import pandas as pd

from tests.conftest import load_script


def test_embed_text_composes_name_categories_summary():
    e = load_script("08_place_embeddings")
    row = pd.Series({"name": "Seoul Bulgogi", "categories": ["korean_restaurant", "restaurant"], "summary": "Casual Korean."})
    assert e.embed_text(row) == "Seoul Bulgogi. korean restaurant, restaurant. Casual Korean."
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/08_place_embeddings.py`**

```python
"""Voyage voyage-3 embeddings for every place → pgvector."""
import json

import pandas as pd
import voyageai
from sqlalchemy import text

from ingest import common

MODEL = "voyage-3"
BATCH = 128


def embed_text(row: pd.Series) -> str:
    cats = ", ".join(c.replace("_", " ") for c in (row.get("categories") or []))
    parts = [row["name"], cats, row.get("summary") or ""]
    return ". ".join(p for p in parts if p).rstrip(".") + "."


def main():
    args = common.cli(__doc__)
    places = common.load("places")
    if args.limit:
        places = places.head(args.limit)
    cache = common.RAW / "voyage/embeddings.jsonl"
    cache.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if cache.exists():
        for line in cache.read_text().splitlines():
            r = json.loads(line)
            done[r["id"]] = r["v"]
    todo = places[~places.id.isin(done)]
    vo = voyageai.Client()
    with cache.open("a") as f:
        for i in range(0, len(todo), BATCH):
            chunk = todo.iloc[i:i + BATCH]
            vecs = vo.embed([embed_text(r) for _, r in chunk.iterrows()], model=MODEL, input_type="document").embeddings
            for pid, v in zip(chunk.id, vecs):
                done[pid] = v
                f.write(json.dumps({"id": pid, "v": v}) + "\n")
    out = pd.DataFrame({"id": places.id, "embedding": [done[i] for i in places.id]})
    common.save(out, "place_embeddings")
    if not args.no_db:
        with common.engine().begin() as con:
            for pid, v in zip(out.id, out.embedding):
                con.execute(text("UPDATE places SET embedding = :v WHERE id = :id"), {"v": json.dumps(list(v)), "id": pid})
    print(f"embeddings: {len(out)} places, model {MODEL}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, smoke, full**

Run: `pytest tests/test_embeddings.py -q` → PASS. `make ingest STEP=08 ARGS="--limit 10 --no-db"` then `make ingest STEP=08`. Verify: `psql -c "select count(*) from places where embedding is not null"`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ingest): voyage-3 place embeddings into pgvector" && git push
```

---

### Task 12: `09_spend_capacity.py`

**Files:**
- Create: `ingest/cex_food_away.yaml`, `ingest/09_spend_capacity.py`, `tests/test_spend.py`

**Interfaces:**
- Produces: `PROC/spend.parquet` with `h3, spending_capacity, local_price_1..4`. Function `capacity(acs_row) -> float` and `price_profile(places, cells) -> DataFrame`.

- [ ] **Step 1: Write `ingest/cex_food_away.yaml`** (BLS CEX 2023, Table 1203 "Income before taxes", food away from home, USD per consumer unit per year; verify figures against the published table and adjust)

```yaml
# annual food-away-from-home spend per household by income bracket (approximate; verify against BLS CEX 2023 Table 1203)
income_lt25k: 1500
income_25_50k: 2300
income_50_75k: 3100
income_75_100k: 3900
income_100_150k: 5000
income_150k_plus: 7800
```

- [ ] **Step 2: Failing tests**

`tests/test_spend.py`:
```python
import pandas as pd

from tests.conftest import load_script


def test_capacity_weights_brackets_by_households():
    s = load_script("09_spend_capacity")
    row = pd.Series({"hh_count": 100, "income_lt25k": 0.5, "income_25_50k": 0.5, "income_50_75k": 0,
                     "income_75_100k": 0, "income_100_150k": 0, "income_150k_plus": 0})
    assert s.capacity(row) == 100 * (0.5 * 1500 + 0.5 * 2300)


def test_price_profile_shares_sum_to_one():
    import h3
    s = load_script("09_spend_capacity")
    c = h3.latlng_to_cell(40.44, -79.99, 9)
    places = pd.DataFrame({"h3": [c, c, c], "price_level": [1, 2, 2], "is_open": [True] * 3})
    out = s.price_profile(places, pd.DataFrame({"h3": [c]})).set_index("h3").loc[c]
    assert abs(out[["local_price_1", "local_price_2", "local_price_3", "local_price_4"]].sum() - 1) < 1e-9
    assert abs(out["local_price_2"] - 2 / 3) < 1e-9
```

- [ ] **Step 3: Run to verify failure.**

- [ ] **Step 4: Write `ingest/09_spend_capacity.py`**

```python
"""Spending capacity (CEX food-away-from-home × ACS income mix) and local price-tier profile."""
import pathlib

import pandas as pd
import yaml

from ingest import common

CEX = yaml.safe_load((pathlib.Path(__file__).with_name("cex_food_away.yaml")).read_text())


def capacity(row: pd.Series) -> float:
    return float(row["hh_count"] * sum(row[k] * v for k, v in CEX.items()))


def price_profile(places: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    p = places[places.is_open & places.price_level.notna()]
    counts = p.groupby(["h3", "price_level"]).size().unstack(fill_value=0).reindex(columns=[1, 2, 3, 4], fill_value=0)
    out = pd.DataFrame({"h3": cells.h3}).set_index("h3")
    for lvl in [1, 2, 3, 4]:
        s = counts[lvl].reindex(out.index, fill_value=0.0) if lvl in counts else pd.Series(0.0, index=out.index)
        out[f"local_price_{lvl}"] = common.disk_sum(s, 2)
    tot = out.sum(axis=1).replace(0, pd.NA)
    for lvl in [1, 2, 3, 4]:
        out[f"local_price_{lvl}"] = (out[f"local_price_{lvl}"] / tot).fillna(0.0).astype(float)
    return out.reset_index()


def main():
    args = common.cli(__doc__)
    acs = common.load("acs")
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    spend = acs.set_index("h3").reindex(cells.h3).fillna(0)
    out = pd.DataFrame({"h3": cells.h3, "spending_capacity": [capacity(r) for _, r in spend.iterrows()]})
    out = out.merge(price_profile(common.load("places"), cells), on="h3")
    common.save(out, "spend")
    print(f"spend: {len(out)} cells, capacity total ${out.spending_capacity.sum()/1e9:.2f}B")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests and script, commit**

Run: `pytest tests/test_spend.py -q` → PASS. `make ingest STEP=09`.
```bash
git add -A && git commit -m "feat(ingest): spending capacity and local price profile" && git push
```

---

### Task 13: `10_rent_proxy.py` and `data/rents_manual.csv`

**Files:**
- Create: `data/rents_manual.csv`, `ingest/10_rent_proxy.py`, `tests/test_rent.py`

**Interfaces:**
- Produces: `PROC/rent.parquet` with `h3, est_rent_psf_yr, rent_confidence, rent_source, rent_resolution`. Functions `fit(manual: DataFrame, features: DataFrame) -> tuple[np.ndarray, float]` (coefficients, R²), `predict(coef, features) -> Series`.

- [ ] **Step 1: Create `data/rents_manual.csv`**

Header: `address,lat,lng,rent_psf_yr,sqft,source_url,collected_on`. Collect 20–50 current retail/restaurant asking rents in Allegheny County from broker listing pages you have permission to read (broker PDFs, LoopNet pages viewed manually — copy numbers by hand, do not scrape). Spread across Oakland, Shadyside, South Side, Lawrenceville, Strip District, Downtown, Squirrel Hill, Bloomfield, Robinson, Monroeville, McKnight Rd. This is a manual task for Dev 1 during ingest hours; the script works with as few as 8 rows.

- [ ] **Step 2: Failing test**

`tests/test_rent.py`:
```python
import numpy as np
import pandas as pd

from tests.conftest import load_script


def test_fit_recovers_linear_relationship():
    r = load_script("10_rent_proxy")
    feats = pd.DataFrame({"zori": [1000, 1500, 2000, 2500], "walkable_poi_density_pct": [10, 40, 60, 90]})
    manual = pd.DataFrame({"rent_psf_yr": 5 + 0.01 * feats.zori + 0.1 * feats.walkable_poi_density_pct})
    coef, r2 = r.fit(manual, feats)
    assert r2 > 0.99
    pred = r.predict(coef, feats)
    assert np.allclose(pred, manual.rent_psf_yr, atol=1e-6)
```

- [ ] **Step 3: Run to verify failure.**

- [ ] **Step 4: Write `ingest/10_rent_proxy.py`**

```python
"""Rent estimate per cell: regression of hand-collected asking rents on ZORI (ZIP) + walkability. Always labeled estimate."""
import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from ingest import common

ZORI_URL = "https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv"
ZCTA_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"
FEATS = ["zori", "walkable_poi_density_pct"]


def zori_by_zip() -> pd.DataFrame:
    path = common.RAW / "zillow/zori_zip.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(ZORI_URL, timeout=120).content)
    df = pd.read_csv(path, dtype={"RegionName": str})
    df = df[(df.State == "PA")]
    last = [c for c in df.columns if c[:2] == "20"][-1]
    return df[["RegionName", last]].rename(columns={"RegionName": "zip", last: "zori"})


def zip_per_cell(cells: pd.DataFrame) -> pd.Series:
    path = common.RAW / "tiger/cb_2020_us_zcta520_500k.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(ZCTA_URL, timeout=600).content)
    z = gpd.read_file(f"zip://{path}")
    z = z[z.ZCTA5CE20.str.startswith("15")][["ZCTA5CE20", "geometry"]]
    pts = gpd.GeoDataFrame(cells[["h3"]], geometry=gpd.points_from_xy(cells.lng, cells.lat), crs="EPSG:4326")
    j = gpd.sjoin(pts, z, how="left", predicate="within")
    return j.drop_duplicates("h3").set_index("h3")["ZCTA5CE20"]


def fit(manual: pd.DataFrame, feats: pd.DataFrame) -> tuple[np.ndarray, float]:
    X = np.column_stack([np.ones(len(feats)), feats[FEATS].values.astype(float)])
    y = manual.rent_psf_yr.values.astype(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss_res, ss_tot = ((y - pred) ** 2).sum(), ((y - y.mean()) ** 2).sum()
    return coef, 1 - ss_res / ss_tot if ss_tot else 0.0


def predict(coef: np.ndarray, feats: pd.DataFrame) -> pd.Series:
    X = np.column_stack([np.ones(len(feats)), feats[FEATS].values.astype(float)])
    return pd.Series(X @ coef, index=feats.index)


def main():
    args = common.cli(__doc__)
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    osm = common.load("osm_cells").set_index("h3").reindex(cells.h3)
    feats = pd.DataFrame({"h3": cells.h3.values})
    feats["zip"] = zip_per_cell(cells).reindex(cells.h3).values
    feats = feats.merge(zori_by_zip(), on="zip", how="left")
    feats["zori"] = feats.zori.fillna(feats.zori.median())
    feats["walkable_poi_density_pct"] = common.pct(osm.walkable_poi_density.fillna(0)).values
    manual = common.points_to_h3(pd.read_csv(common.ROOT / "data/rents_manual.csv"))
    mf = manual.merge(feats, on="h3", how="inner")
    coef, r2 = fit(mf, mf)
    out = pd.DataFrame({"h3": feats.h3, "est_rent_psf_yr": predict(coef, feats).clip(8, 80).values})
    out["rent_confidence"] = float(np.clip(0.3 + 0.5 * r2, 0.3, 0.8))
    out["rent_source"] = "zori+manual_regression"
    out["rent_resolution"] = "zip"
    common.save(out, "rent")
    print(f"rent: n_manual={len(mf)} r2={r2:.2f} median est ${out.est_rent_psf_yr.median():.0f}/sqft/yr")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests and script, commit**

Run: `pytest tests/test_rent.py -q` → PASS. `make ingest STEP=10` (ZCTA download ~70 MB). If `rents_manual.csv` has < 8 rows the R² is meaningless; note the printed R² in `brain/progress.md`.
```bash
git add -A && git commit -m "feat(ingest): rent estimate regression from ZORI and manual asking rents" && git push
```

---

### Task 14: `11_cuisine_affinity.py`

**Files:**
- Create: `ingest/11_cuisine_affinity.py`, `tests/test_affinity.py`

**Interfaces:**
- Produces: `PROC/affinity.parquet` with `h3, cuisine_affinity` (dict cuisine_key → 0–100). Function `affinity(places, cells, price_profile) -> DataFrame`.

- [ ] **Step 1: Failing test**

`tests/test_affinity.py`:
```python
import h3
import pandas as pd

from tests.conftest import load_script


def test_affinity_higher_near_engaged_same_cuisine():
    a = load_script("11_cuisine_affinity")
    c1 = h3.latlng_to_cell(40.44, -79.99, 9)
    c2 = h3.latlng_to_cell(40.55, -80.10, 9)  # far away
    places = pd.DataFrame({"h3": [c1], "cuisine_key": ["korean"], "reviews": [500], "rating": [4.6],
                           "price_level": [2], "is_open": [True]})
    cells = pd.DataFrame({"h3": [c1, c2]})
    pp = pd.DataFrame({"h3": [c1, c2], "local_price_1": [0, 0], "local_price_2": [1, 1],
                       "local_price_3": [0, 0], "local_price_4": [0, 0]})
    out = a.affinity(places, cells, pp).set_index("h3")
    assert out.loc[c1, "cuisine_affinity"]["korean"] > out.loc[c2, "cuisine_affinity"]["korean"]
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/11_cuisine_affinity.py`**

```python
"""Observed cuisine affinity (proposal §3.4): engagement of same/complementary cuisines nearby + price compatibility.
No demographic or ancestry inputs."""
import numpy as np
import pandas as pd

from ingest import common, taxonomy


def affinity(places: pd.DataFrame, cells: pd.DataFrame, price_profile: pd.DataFrame) -> pd.DataFrame:
    tax = taxonomy.load()["cuisines"]
    p = places[places.is_open & places.cuisine_key.notna()].copy()
    p["eng"] = np.log1p(p.reviews.fillna(0)) * p.rating.fillna(3.5)
    eng = p.groupby(["h3", "cuisine_key"])["eng"].sum().unstack(fill_value=0.0)
    idx = pd.Index(cells.h3)
    disk = {}
    for c in eng.columns:
        disk[c] = common.disk_sum(eng[c].reindex(idx, fill_value=0.0), 2)
    pp = price_profile.set_index("h3").reindex(idx).fillna(0.0)
    result = {c: pd.Series(0.0, index=idx) for c in tax}
    for c, spec in tax.items():
        own = disk.get(c, pd.Series(0.0, index=idx))
        comp = sum((disk.get(k, pd.Series(0.0, index=idx)) for k in spec.get("complementary", [])), pd.Series(0.0, index=idx))
        tier = spec.get("default_price_tier", 2)
        price_ok = pp[f"local_price_{tier}"] + 0.5 * (pp.get(f"local_price_{max(tier - 1, 1)}", 0) + pp.get(f"local_price_{min(tier + 1, 4)}", 0))
        raw = own + 0.5 * comp + price_ok * (own.mean() if own.mean() > 0 else 1.0)
        result[c] = common.pct(raw)
    out = pd.DataFrame({"h3": idx})
    out["cuisine_affinity"] = [{c: float(result[c][h]) for c in tax} for h in idx]
    return out


def main():
    args = common.cli(__doc__)
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    out = affinity(common.load("places"), cells, common.load("spend"))
    common.save(out, "affinity")
    print(f"affinity: {len(out)} cells × {len(out.cuisine_affinity.iloc[0])} cuisines")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests and script, commit**

Run: `pytest tests/test_affinity.py -q` → PASS. `make ingest STEP=11`.
```bash
git add -A && git commit -m "feat(ingest): observed cuisine affinity per cell" && git push
```

---

### Task 15: `12_build_features.py`

**Files:**
- Create: `ingest/12_build_features.py`, `tests/test_build_features.py`

**Interfaces:**
- Consumes: `acs, lodes, osm_cells, activity_cells, spend, rent, affinity, places` parquet.
- Produces: `PROC/cell_features.parquet` with every column in `contracts/cell_features.md` (numeric columns plus `*_pct`), `traffic_source`, `rent_source`, `rent_resolution`, `rent_confidence`, `cuisine_affinity`, and DB table `cell_features`. Functions `join_all(parts: dict[str, DataFrame], cells) -> DataFrame`, `add_percentiles(df) -> DataFrame`, `NUMERIC: list[str]`, `SOURCE: dict[str, str]`, `RESOLUTION: dict[str, str]`.

- [ ] **Step 1: Failing test on a tiny synthetic set**

`tests/test_build_features.py`:
```python
import h3
import pandas as pd

from tests.conftest import load_script


def _cells(n=3):
    base = h3.latlng_to_cell(40.44, -79.99, 9)
    cs = list(h3.grid_disk(base, 1))[:n]
    return pd.DataFrame({"h3": cs, "lat": [h3.cell_to_latlng(c)[0] for c in cs], "lng": [h3.cell_to_latlng(c)[1] for c in cs]})


def test_join_and_percentiles_cover_contract_columns():
    b = load_script("12_build_features")
    cells = _cells()
    parts = {name: pd.DataFrame({"h3": cells.h3}) for name in
             ["acs", "lodes", "osm_cells", "activity_cells", "spend", "rent", "affinity"]}
    for col, part_name in b.PART_OF.items():
        parts[part_name][col] = [1.0, 2.0, 3.0]
    parts["activity_cells"]["traffic_source"] = "proxy"
    parts["rent"]["rent_source"], parts["rent"]["rent_resolution"], parts["rent"]["rent_confidence"] = "x", "zip", 0.5
    parts["affinity"]["cuisine_affinity"] = [{"korean": 50.0}] * 3
    places = pd.DataFrame({"h3": [cells.h3[0]], "is_open": [True]})
    df = b.add_percentiles(b.join_all(parts, cells, places))
    for col in b.NUMERIC:
        assert col in df.columns, col
        assert f"{col}_pct" in df.columns, col
        assert df[f"{col}_pct"].between(0, 100).all()
    assert not df[b.NUMERIC].isna().any().any()
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `ingest/12_build_features.py`**

```python
"""Join every per-cell parquet into cell_features with metro-wide percentiles, provenance maps, and DB upsert."""
import json

import pandas as pd
from sqlalchemy import text

from ingest import common

ACS = ["pop_total", "hh_count", "median_hh_income", "income_lt25k", "income_25_50k", "income_50_75k",
       "income_75_100k", "income_100_150k", "income_150k_plus", "pct_age_18_24", "pct_age_25_34", "pct_age_35_54",
       "pct_age_55p", "pct_families_with_kids", "avg_hh_size", "pct_no_vehicle", "pct_renters",
       "pct_bachelors_plus", "pct_students"]
LODES = ["workers_daytime", "workers_high_wage"]
ANCHOR_TYPES = ["university", "school", "office", "hospital", "hotel", "bar", "nightclub", "mall", "cinema",
                "stadium", "park", "attraction", "transit_station"]
OSM = [f"anchor_{k}" for k in ANCHOR_TYPES] + \
      [f"dist_to_{k}_km" for k in ["university", "hospital", "transit_station", "stadium"]] + \
      ["transit_daily_trips", "main_road_frontage", "parking_lots", "walkable_poi_density", "poi_density"] + \
      [f"dist_to_{k}_km" for k in ["wholesale", "supermarket", "seafood", "butcher", "greengrocer", "asian_grocer", "italian_grocer"]]
ACTIVITY = [f"activity_{d}" for d in ["morning", "lunch", "afternoon", "dinner", "late_night", "weekend"]]
SPEND = ["spending_capacity", "local_price_1", "local_price_2", "local_price_3", "local_price_4"]
RENT = ["est_rent_psf_yr"]
DERIVED = ["restaurants_open"]

NUMERIC = ACS + LODES + OSM + ACTIVITY + SPEND + RENT + DERIVED
PART_OF = {**{c: "acs" for c in ACS}, **{c: "lodes" for c in LODES}, **{c: "osm_cells" for c in OSM},
           **{c: "activity_cells" for c in ACTIVITY}, **{c: "spend" for c in SPEND}, **{c: "rent" for c in RENT}}
SOURCE = {**{c: "acs_5yr_2023" for c in ACS}, **{c: "lodes_wac_2021" for c in LODES},
          **{c: "osm_overpass" for c in OSM if not c.startswith("transit_daily")}, "transit_daily_trips": "gtfs_prt",
          **{c: "besttime_or_proxy" for c in ACTIVITY}, **{c: "cex_x_acs" for c in SPEND[:1]},
          **{c: "google_price_level" for c in SPEND[1:]}, "est_rent_psf_yr": "zori_manual_regression",
          "restaurants_open": "wprdc_google"}
RESOLUTION = {**{c: "block_group" for c in ACS + LODES}, **{c: "point" for c in OSM + ACTIVITY + SPEND[1:] + DERIVED},
              "spending_capacity": "block_group", "est_rent_psf_yr": "zip"}
DIST_FILL = 25.0


def join_all(parts: dict[str, pd.DataFrame], cells: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    df = cells[["h3"]].copy()
    for name, part in parts.items():
        df = df.merge(part, on="h3", how="left")
    open_counts = places[places.is_open].groupby("h3").size()
    df["restaurants_open"] = common.disk_sum(open_counts.reindex(df.h3, fill_value=0.0), 1).values
    for c in NUMERIC:
        if c not in df:
            df[c] = 0.0
        df[c] = df[c].fillna(DIST_FILL if c.startswith("dist_to_") else 0.0).astype(float)
    df["traffic_source"] = df.get("traffic_source", pd.Series("proxy", index=df.index)).fillna("proxy")
    df["rent_source"] = df.get("rent_source", pd.Series(None, index=df.index))
    df["rent_resolution"] = df.get("rent_resolution", pd.Series(None, index=df.index))
    df["rent_confidence"] = df.get("rent_confidence", pd.Series(0.0, index=df.index)).fillna(0.0)
    df["cuisine_affinity"] = df.get("cuisine_affinity", pd.Series([{}] * len(df), index=df.index))
    df["cuisine_affinity"] = df.cuisine_affinity.apply(lambda v: v if isinstance(v, dict) else {})
    return df


def add_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    for c in NUMERIC:
        s = df[c]
        df[f"{c}_pct"] = (100.0 - common.pct(s)) if c.startswith("dist_to_") else common.pct(s)
    return df


def main():
    args = common.cli(__doc__)
    cells = common.load_cells()
    if args.limit:
        cells = cells.head(args.limit)
    parts = {n: common.load(n) for n in ["acs", "lodes", "osm_cells", "activity_cells", "spend", "rent", "affinity"]}
    df = add_percentiles(join_all(parts, cells, common.load("places")))
    common.save(df, "cell_features")
    if not args.no_db:
        num_cols = NUMERIC + [f"{c}_pct" for c in NUMERIC]
        rows = [{"h3": r.h3, "features": json.dumps({c: float(r[c]) for c in num_cols}),
                 "cuisine_affinity": json.dumps(r.cuisine_affinity),
                 "activity_by_daypart": json.dumps({d.removeprefix("activity_"): float(r[d]) for d in ACTIVITY}),
                 "traffic_source": r.traffic_source, "rent_source": r.rent_source, "rent_resolution": r.rent_resolution,
                 "rent_confidence": float(r.rent_confidence), "source": json.dumps(SOURCE), "resolution": json.dumps(RESOLUTION)}
                for _, r in df.iterrows()]
        with common.engine().begin() as con:
            con.execute(text("DELETE FROM cell_features"))
            con.execute(text("""INSERT INTO cell_features (h3, features, cuisine_affinity, activity_by_daypart, traffic_source,
                                rent_source, rent_resolution, rent_confidence, source, resolution)
                                VALUES (:h3, CAST(:features AS jsonb), CAST(:cuisine_affinity AS jsonb),
                                CAST(:activity_by_daypart AS jsonb), :traffic_source, :rent_source, :rent_resolution,
                                :rent_confidence, CAST(:source AS jsonb), CAST(:resolution AS jsonb))"""), rows)
    print(f"cell_features: {len(df)} cells × {len(NUMERIC)} numeric columns (+pct)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests and script**

Run: `pytest tests/test_build_features.py -q` → PASS. `make ingest STEP=12`. Verify: `psql -c "select count(*), count(*) filter (where traffic_source='real') from cell_features"`.

- [ ] **Step 5: Cross-check against the contract**

Run:
```bash
.venv/bin/python - <<'EOF'
import re, pathlib, pandas as pd
md = pathlib.Path("contracts/cell_features.md").read_text()
rows = [l for l in md.splitlines() if l.startswith("| ") and not l.startswith("| Column")]
want = {w for l in rows for w in re.findall(r"[a-z][a-z0-9_]+", l.split("|")[1])}
want -= {"cuisine_affinity", "traffic_source", "rent_source", "rent_resolution", "rent_confidence"}
have = set(pd.read_parquet("data/processed/cell_features.parquet").columns)
print("in contract, missing from parquet:", sorted(want - have))
EOF
```
Expected: `[]`. Fix any gap in `contracts/cell_features.md` or the script until they agree.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(ingest): build cell_features with percentiles and provenance" && git push
```

---

### Task 16: `sanity.py`, fixtures, data handoff

**Files:**
- Create: `ingest/sanity.py`, `ingest/make_fixtures.py`, `data/fixtures/cell_features_sample.parquet`, `data/fixtures/recommend_sample.json`, `tests/test_fixtures.py`

**Interfaces:**
- Produces: PNG heatmaps under `data/sanity/` (gitignored by `*.png`), fixtures used by the backend and web tracks. `recommend_sample.json` validates against `contracts/recommend_response.json`.

- [ ] **Step 1: Write `ingest/sanity.py`**

```python
"""Static heatmaps to eyeball the feature store. Oakland / Downtown / Strip should be hot."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ingest import common

COLS = ["pop_total", "workers_daytime", "poi_density", "restaurants_open", "activity_dinner", "est_rent_psf_yr",
        "spending_capacity", "transit_daily_trips"]


def main():
    df = common.load("cell_features").merge(common.load_cells(), on="h3")
    out = common.ROOT / "data/sanity"
    out.mkdir(exist_ok=True)
    for c in COLS:
        fig, ax = plt.subplots(figsize=(8, 7))
        ax.scatter(df.lng, df.lat, c=df[f"{c}_pct"], s=3, cmap="viridis")
        ax.set_title(c)
        ax.set_aspect(1.3)
        fig.savefig(out / f"{c}.png", dpi=110)
        plt.close(fig)
    print(f"wrote {len(COLS)} heatmaps to {out}")


if __name__ == "__main__":
    main()
```

Run: `make sanity`, open the PNGs, confirm the expected hot spots. Note anomalies in `brain/lessons.md`.

- [ ] **Step 2: Failing fixture test**

`tests/test_fixtures.py`:
```python
import json

import pandas as pd

from ingest import common


def test_cell_features_sample_exists_and_has_pct_columns():
    df = pd.read_parquet(common.FIXTURES / "cell_features_sample.parquet")
    assert 150 <= len(df) <= 400
    assert "pop_total_pct" in df.columns and "cuisine_affinity" in df.columns


def test_recommend_sample_validates():
    from api.models import RecommendResponse
    data = json.loads((common.FIXTURES / "recommend_sample.json").read_text())
    r = RecommendResponse.model_validate(data)
    assert len(r.zones) >= 3 and r.cells["type"] == "FeatureCollection"
```

- [ ] **Step 3: Write `ingest/make_fixtures.py`**

```python
"""Fixtures for the backend and web tracks: ~200 real cells around Oakland + a fake-scored RecommendResponse."""
import json

import h3
import numpy as np
import pandas as pd

from ingest import common

CENTER = (40.4406, -79.9600)  # Oakland
DEMO_PROFILE = {
    "concept_name": "Korean street food", "cuisines": ["korean"], "subcuisine": ["street_food"],
    "substitute_cuisines": ["japanese", "chinese"], "complementary_cuisines": ["bubble_tea"],
    "service_format": "fast_casual", "price_tier": 1, "avg_ticket_usd": 13,
    "dayparts": {"lunch": 0.3, "dinner": 0.4, "late_night": 0.3}, "customer_archetypes": ["students", "young_adults"],
    "target_age_mix": {"18_24": 0.5, "25_34": 0.3}, "dine_in_importance": 0.4, "takeout_importance": 0.8,
    "delivery_importance": 0.7, "parking_importance": 0.1, "pedestrian_importance": 0.9, "transit_importance": 0.6,
    "nightlife_importance": 0.6, "office_importance": 0.2, "university_importance": 0.9, "family_importance": 0.1,
    "visibility_importance": 0.6, "income_fit": "low_to_medium", "catchment": "walk", "catchment_tau_min": 8,
    "footprint_sqft": [800, 1500], "seats": 24, "supplier_types": ["asian_grocer", "wholesale"],
    "direct_competitor_description": "casual Korean restaurants, Korean fried chicken, bibimbap, tteokbokki",
    "is_franchise": False, "proposed_weights": {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
    "confidence": 0.9, "clarifying_questions": []}
KEYS = ["D", "C", "T", "A", "S_spend", "K", "Sup"]


def main():
    rng = np.random.default_rng(7)
    center = h3.latlng_to_cell(*CENTER, 9)
    disk = set(h3.grid_disk(center, 8))
    cf = common.load("cell_features")
    sample = cf[cf.h3.isin(disk)].head(250)
    sample.to_parquet(common.FIXTURES / "cell_features_sample.parquet", index=False)

    feats, zone_id = [], {}
    scores = {h: rng.uniform(20, 95, size=7) for h in sample.h3}
    ranked = sorted(sample.h3, key=lambda h: -float(np.dot(list(DEMO_PROFILE["proposed_weights"].values()), scores[h])))
    for i, h in enumerate(ranked[:5]):
        for c in h3.grid_disk(h, 1):
            zone_id.setdefault(c, i + 1)
    for h in sample.h3:
        s = dict(zip(KEYS, map(float, scores[h])))
        total = float(np.dot(list(DEMO_PROFILE["proposed_weights"].values()), list(s.values())))
        feats.append({"type": "Feature", "geometry": common.cell_polygon(h).__geo_interface__,
                      "properties": {"h3": h, "total": total, **s, "confidence": 0.6, "zone_id": zone_id.get(h)}})
    zones = []
    for i, h in enumerate(ranked[:5]):
        s = dict(zip(KEYS, map(float, scores[h])))
        zones.append({"zone_id": i + 1, "name": f"Zone {i + 1} (fixture)", "total": float(np.dot(list(DEMO_PROFILE["proposed_weights"].values()), list(s.values()))),
                      "best_h3": h, "subscores": s, "confidence": 0.6,
                      "drivers": ["Student demand 91st pct", "Late-night traffic 84th pct", "No direct Korean competitors"],
                      "risks": ["Rent estimate low confidence", "Parking 12th pct"],
                      "gap": {"demand": 82, "supply": 20, "gap": 62}, "gap_flag": True,
                      "competitors_direct": [], "competitors_indirect": [{"id": "google:x", "name": "Sushi Fuku", "distance_m": 210, "similarity": 0.62, "rating": 4.4, "reviews": 800}],
                      "anchors": [{"name": "University of Pittsburgh", "type": "university", "distance_m": 300}],
                      "est_rent_psf_yr": 28.0, "rent_confidence": 0.5})
    resp = {"analysis_id": "fixture-0001", "profile": DEMO_PROFILE,
            "weights": DEMO_PROFILE["proposed_weights"],
            "cells": {"type": "FeatureCollection", "features": feats}, "zones": zones, "backtest_rho": None}
    (common.FIXTURES / "recommend_sample.json").write_text(json.dumps(resp))
    print(f"fixtures: {len(sample)} cells, {len(zones)} zones")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run, test, commit**

Run: `make fixtures && pytest tests/test_fixtures.py -q` → PASS.

- [ ] **Step 5: Package processed data for teammates**

```bash
du -sh data/processed
```
If under 50 MB: `git add data/processed`. Otherwise: `zip -r data/processed.zip data/processed` and share the zip out-of-band; teammates run `make restore-data`. Record which path was taken in `brain/team.md`.

- [ ] **Step 6: Update `brain/` and commit**

Tick Phase 1 tasks in `brain/tasks.md`; append the session summary and backtest-relevant numbers (row counts, R², BestTime venue count) to the Dev 1 section of `brain/progress.md`; add anything surprising to `brain/lessons.md`.

```bash
git add -A && git commit -m "feat(ingest): sanity heatmaps, fixtures for backend/web tracks, data handoff" && git push
```

---

## Self-review notes

- **Spec coverage:** Spec §2 (layout, contracts) → Tasks 1–2. §3 pipeline rows → Tasks 4–15 (Foursquare deliberately skipped per D7; `06_foursquare.py` not created). Sanity + fixtures → Task 16. §6 team files and agents → Task 3. Spec §4 (backend) and §5 (web) are out of scope for this plan and get their own plans once Dev 2 / Dev 3 join (or when foundation finishes early).
- **Type consistency:** `common.load/save/load_cells/cells_gdf/area_weight/points_to_h3/disk_sum/pct/cli` are used with the same signatures across Tasks 5–16. `NUMERIC`/`PART_OF` in Task 15 match the columns emitted by Tasks 5–13 and listed in `contracts/cell_features.md`.
- **Known verification points (not placeholders):** WPRDC resource id and column names (Task 7 Step 3), PRT GTFS zip URL (Task 8), CEX bracket values (Task 12), ACS variable codes (Task 5; confirm at `https://api.census.gov/data/2023/acs/acs5/variables.html` if a fetch returns errors).
