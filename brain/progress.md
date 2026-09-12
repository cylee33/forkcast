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

**Built (Tasks 1–8).**

| Task | What landed |
|---|---|
| 1 | Repo skeleton, Docker Postgres with PostGIS and pgvector, the full schema, GitHub Actions CI |
| 2 | `contracts/` frozen: `ConceptProfile`, `RecommendResponse`, the `cell_features` column list, the `places` table, with Pydantic and TypeScript mirrors |
| 3 | `brain/team.md`, `brain/demo.md`, four role files under `.claude/agents/` |
| 4 | `ingest/common.py` (paths, engine, area weighting, H3 helpers, percentiles) and `00_grid.py`; 18,275 cells are in the `geo_cells` table |
| 5 | `01_census_acs.py` and its tests; the data run is blocked on a Census key |
| 6 | `02_lodes.py`; 686,253 daytime workers, peaking Downtown |
| 7 | `03_wprdc_food.py` plus a 49-cuisine taxonomy; 15,215 facilities, 9,970 of them open |
| 8 | `04_osm_pois.py`; anchors, suppliers, parking, walkability, road frontage and transit for all 18,275 cells, plus GTFS |

Twenty-two tests pass and `ruff check .` is clean.

**The feature store checks out against real geography.** Downtown leads walkability
and transit, the South Side has the most bars, Oakland has the universities, and the
outer suburbs are empty. Supplier distances run from a third of a kilometre in the
Strip District to over twenty in Sewickley.

**Eight plan defects were found and corrected during execution**, each recorded in the
execution ledger with the reasoning and the cost of being wrong. The notable ones: the
plan's assumed WPRDC column names and open/closed signal were both wrong, its GTFS URL
was dead, Overpass refuses requests that carry no User-Agent header, and one snippet
would have silently dropped four of the five hand-listed suppliers.

**Blocked on keys.** Every remaining ingest task needs a key that is not yet in
`.env`, so this is where the work stops.

| Key | Blocks | Why it matters |
|---|---|---|
| `CENSUS_API_KEY` | Task 5's data run, then 12 and 15 | Free and instant. The API refuses keyless requests |
| `GOOGLE_PLACES_API_KEY` | Tasks 9, 11 and 14 | The most valuable one. About $117 for roughly 3,600 requests, inside Google's free monthly credit |
| `VOYAGE_API_KEY` | Task 11 | Embeddings for competitor similarity |
| `BESTTIME_API_KEY_PRIVATE` | Task 10's real traffic | The proxy path runs without it |

Google's key is the urgent one. Restaurant names alone identify cuisine for only
48% of open places, and just three Korean restaurants match, which would leave the
Korean demo concept with no competitors to score against. Google's place types are
what fix that.

**Pick up here next:** Task 9 (`05_google_places.py`) as soon as a Google key exists,
then 11 and 14 behind it. Task 10 can run its proxy path at any time. The
task-by-task ledger with review findings and rulings lives at
`.superpowers/sdd/2026-09-12-foundation-data-pipeline/progress.md`; the checkbox
state lives in `brain/tasks.md`.

## Dev 2

_Not yet started. Backend track, Phase 2 of `brain/tasks.md`._

## Dev 3

_Not yet started. Web track, Phase 3 of `brain/tasks.md`._
