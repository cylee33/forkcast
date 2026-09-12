# Forkcast — Progress

Each developer appends to their own section only, so the file does not
conflict on merge.

## Dev 1 (cylee)

### 2026-09-12 — Session 1

**Planning.** Read `forkcast-proposal.md` and turned it into decisions: a real
24-hour hackathon, three developers, Pittsburgh only, reverse mode in the core
scope, properties cut, compare table and report modal as stretch. Wrote the
spec to `docs/superpowers/specs/2026-09-12-forkcast-design.md` and the
16-task foundation plan to
`docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`.

**Repo.** Created `cylee33/forkcast` on GitHub, public. Work happens on the
`data/foundation` branch and merges to `main` at task-group boundaries.

**Environment.** Installed `uv` with Python 3.11, plus Colima and the Docker
CLI, because the machine had neither a usable interpreter nor a container
runtime. See `brain/lessons.md` for the details and the two image fixes.

**Built (Tasks 1–5).**

| Task | What landed |
|---|---|
| 1 | Repo skeleton, Docker Postgres with PostGIS and pgvector, the full schema, GitHub Actions CI |
| 2 | `contracts/` frozen: `ConceptProfile`, `RecommendResponse`, the `cell_features` column list, the `places` table, with Pydantic and TypeScript mirrors |
| 3 | `brain/team.md`, `brain/demo.md`, four role files under `.claude/agents/` |
| 4 | `ingest/common.py` (paths, engine, area weighting, H3 helpers, percentiles) and `00_grid.py`; 18,275 cells are in the `geo_cells` table |
| 5 | `01_census_acs.py` and its tests; the data run is blocked on a Census key |

Twelve tests pass and `ruff check .` is clean.

**Blocked.** `01_census_acs.py` cannot fetch without a `CENSUS_API_KEY`. The
code is committed and needs only `make ingest STEP=01` once a key is in
`.env`. Tasks 12 and 15 consume its output, so the key is on the critical path.

**Pick up here next:** Task 6 (`02_lodes.py`), then Tasks 7 and 8, which need
no API keys. Get the Census key and the WPRDC resource id in parallel. The
task-by-task ledger with review findings and rulings lives at
`.superpowers/sdd/2026-09-12-foundation-data-pipeline/progress.md`; the
checkbox state lives in `brain/tasks.md`.

## Dev 2

_Not yet started. Backend track, Phase 2 of `brain/tasks.md`._

## Dev 3

_Not yet started. Web track, Phase 3 of `brain/tasks.md`._
