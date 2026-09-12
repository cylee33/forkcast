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

## Getting set up

1. `git clone https://github.com/cylee33/forkcast && cd forkcast`
2. `brew install uv colima docker docker-compose`, then `colima start --cpu 2 --memory 4`.
   Docker Desktop works too; nothing in the repo depends on which one you run.
3. `make venv` — creates `.venv` on Python 3.11 through `uv` and installs `requirements.txt`.
4. `cp .env.example .env` and fill in the keys Dev 1 shares out of band.
5. `make db-up`, wait for the container to report healthy, then
   `docker compose exec db psql -U forkcast -c "\dt"` should list ten tables.
6. `make test` and `make lint` should both be clean before you start.

Dev 3 does not need the database or any key: set `NEXT_PUBLIC_USE_FIXTURE=1`
and the web app runs off `data/fixtures/recommend_sample.json`.

## Hour-10 checkpoint
- [ ] All three on `main`, `docker compose up`, Korean street-food concept runs end-to-end.
- [ ] `contracts/` frozen.

## Blockers
| Date | Who | Blocker | Status |
|---|---|---|---|
| 2026-09-12 | Dev 1 | No `CENSUS_API_KEY`. The Census API refuses keyless requests, so `01_census_acs.py` cannot produce `acs.parquet`. Tasks 12 and 15 consume it. | Resolved — key set in `.env` |
| 2026-09-12 | Dev 1 | No `WPRDC_FOOD_RESOURCE_ID`. Needed before Task 7 can pull the food-facility list. | Resolved — `112a3821-334d-4f3f-ab40-4de1220b1a0a` |
| 2026-09-12 | Dev 1 | `BESTTIME_API_KEY_PRIVATE` and `GEMINI_API_KEY` not provisioned. They block Tasks 10 and 11; Task 10 still runs its proxy path without a key. `GOOGLE_PLACES_API_KEY` and `CENSUS_API_KEY` are now set. | Open |

## Contract change log
| Date | Who | File | Change |
|---|---|---|---|
| 2026-09-12 | Dev 1 | `contracts/places.md` | `embedding` is now `gemini-embedding-001` at `output_dimensionality=1024` instead of Voyage `voyage-3`. **The column stays `vector(1024)`, so no schema migration and no code change for Dev 2 or Dev 3.** Only the model that fills it changed. Vectors are L2-normalized by the ingest script, because Gemini returns normalized vectors only at its native 3072 dims. |

## Data handoff

`data/raw/` is gitignored and large; do not try to share it. `data/processed/`
is committed while it stays under 50 MB in total, so a clone gets the feature
store with the code. If it outgrows that, Dev 1 switches to a zip plus
`make restore-data` and notes the change here.

| Date | What | How it is shared |
|---|---|---|
| 2026-09-12 | `data/processed/geo_cells.parquet` (2.1 MB, 18,275 cells) | Committed to the repo |
