STEPS := 00_grid 01_census_acs 02_lodes 03_wprdc_food 04_osm_pois 05_google_places 07_besttime 08_place_embeddings 09_spend_capacity 10_rent_proxy 11_cuisine_affinity 12_build_features
PY := .venv/bin/python

.PHONY: venv db-up db-down ingest test lint fixtures sanity restore-data

venv:
	python3 -m venv .venv && $(PY) -m pip install -r requirements.txt

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
