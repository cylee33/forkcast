STEPS := 00_grid 01_census_acs 02_lodes 03_wprdc_food 04_osm_pois 05_google_places 07_besttime 08_place_embeddings 09_spend_capacity 10_rent_proxy 11_cuisine_affinity 12_build_features
PY := .venv/bin/python

.PHONY: venv db-up db-down ingest test lint fixtures sanity restore-data api app demo

venv:
	uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt

db-up:
	docker compose up -d db

db-down:
	docker compose down

ingest:
ifdef STEP
	PYTHONPATH=. $(PY) ingest/$(STEP)*.py $(ARGS)
else
	for s in $(STEPS); do PYTHONPATH=. $(PY) ingest/$$s.py $(ARGS) || exit 1; done
endif

sanity:
	PYTHONPATH=. $(PY) ingest/sanity.py

fixtures:
	PYTHONPATH=. $(PY) ingest/make_fixtures.py

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

restore-data:
	unzip -o data/processed.zip -d data/

api:
	PYTHONPATH=. $(PY) -m uvicorn api.main:app --reload --port 8000

app:
	PYTHONPATH=. $(PY) -m streamlit run app/streamlit_app.py --server.port 8501

demo:
	PYTHONPATH=. $(PY) -m uvicorn api.main:app --port 8000 &
	sleep 2
	PYTHONPATH=. $(PY) -m streamlit run app/streamlit_app.py --server.port 8501
