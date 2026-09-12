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
| 2026-09-12 | Dev 1 | No `CENSUS_API_KEY`. The Census API refuses keyless requests, so `01_census_acs.py` cannot produce `acs.parquet`. Tasks 12 and 15 consume it. | Open — key requested |
| 2026-09-12 | Dev 1 | No `WPRDC_FOOD_RESOURCE_ID`. Needed before Task 7 can pull the food-facility list. | Open |
| 2026-09-12 | Dev 1 | `GOOGLE_PLACES_API_KEY`, `BESTTIME_API_KEY_PRIVATE`, `VOYAGE_API_KEY` not provisioned. They block Tasks 9, 10 and 11; Task 10 still runs its proxy path without a key. | Open |

## Contract change log
| Date | Who | File | Change |
|---|---|---|---|

## Data handoff

`data/raw/` is gitignored and large; do not try to share it. `data/processed/`
is committed while it stays under 50 MB in total, so a clone gets the feature
store with the code. If it outgrows that, Dev 1 switches to a zip plus
`make restore-data` and notes the change here.

| Date | What | How it is shared |
|---|---|---|
| 2026-09-12 | `data/processed/geo_cells.parquet` (2.1 MB, 18,275 cells) | Committed to the repo |
