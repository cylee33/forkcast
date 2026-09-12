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
| `GEMINI_API_KEY` | Task 11, then Phase 2 | Embeddings for competitor similarity, and the LLM for parse, refine and explain |
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

### 2026-09-12 — Session 2

**Provider swap: Anthropic to Gemini.** Decision D12 changed. `gemini-3.8-flash`
now does parse, refine, explain and compare. `gemini-embedding-001` replaces
Voyage `voyage-3` for competitor similarity, at `output_dimensionality=1024` and
`task_type=SEMANTIC_SIMILARITY`. The project is down to one LLM provider and one
`GEMINI_API_KEY`.

No `api/` LLM code existed yet, so nothing had to be rewritten — only
documentation, configuration and the Task 11 brief.

| File | Change |
|---|---|
| `.env`, `.env.example` | `VOYAGE_API_KEY` and `ANTHROPIC_API_KEY` replaced by `GEMINI_API_KEY` |
| `requirements.txt` | `voyageai==0.3.2` out, `google-genai==2.23.0` in; `pydantic` pinned up to `2.13.5` |
| `contracts/places.md` | `embedding` model note; the column stays `vector(1024)` |
| `brain/plan.md`, the spec | D12 rewritten; `concept_parser` now uses Gemini structured output rather than tool-use |
| the foundation plan | Task 11 rewritten against the `google-genai` SDK, plus stack, `.env` and requirements blocks |
| `README.md`, `.claude/agents/data-ingest.md` | key table, model table, agent description |
| `brain/team.md` | contract change log entry; two stale blockers marked resolved |

**`places.embedding` stays `vector(1024)`, so there is no schema migration and
nothing for Dev 2 or Dev 3 to change.** Only the model that fills it differs.

**Two things worth knowing, both recorded in `brain/lessons.md`.** Gemini returns
normalized vectors only at its native 3072 dimensions, so the ingest script must
L2-normalize what it gets back at 1024. And `google-genai` requires
`pydantic>=2.12.5` against a repo pinned at `2.9.2`, so a fresh `make venv` would
have failed to resolve until the pin moved.

Verified after the change: `ruff check .` clean, 22 tests pass, and the full
`requirements.txt` set resolves with no conflict.

**Keys.** `CENSUS_API_KEY` and `GOOGLE_PLACES_API_KEY` are now set, which
resolves the two blockers that stopped Session 1. `GEMINI_API_KEY` is not yet
set. `BESTTIME_API_KEY_PRIVATE` remains optional.

**Pick up here next:** Task 10 (`07_besttime.py`) needs no key at all. Task 5's
data run, then Task 9 (`05_google_places.py`), then Task 12, are all unblocked
now that Census and Google keys exist. Task 11 waits on `GEMINI_API_KEY`, and
Task 13 waits on the hand-collected rents in `data/rents_manual.csv`.


## Dev 2

_Not yet started. Backend track, Phase 2 of `brain/tasks.md`._

## Dev 3

_Not yet started. Web track, Phase 3 of `brain/tasks.md`._
