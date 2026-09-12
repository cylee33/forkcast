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


### 2026-09-12 — Session 3 (final whole-branch review fix wave)

**All sixteen Phase 1 tasks are now complete**, including Task 16
(`sanity.py` + fixtures), which Session 2 had left unchecked. `brain/tasks.md`
is corrected to match.

**Seven review findings fixed, applied locally, no live API calls made** (every
key in `.env` is quota-exhausted or spend-sensitive; `CENSUS_API_KEY` was not
called either — `01_census_acs.py` re-parsed the already-cached
`data/raw/acs/bg_2023.json`):

1. **The Census jam-value defect (headline finding).** `-666666666` ("estimate
   not available") was being `clip(lower=0)`-ed into a plausible $0 income.
   Fixed at three points: `01_census_acs.py` masks any value at or below the
   smallest ACS jam sentinel to NaN before clipping; `common.py`'s
   `area_weight` now divides each intensive column by its own per-column
   non-null intersection area, not the shared `_ia` sum, so a cell whose only
   source is a jam block group comes out NaN instead of diluted-toward-zero;
   and `12_build_features.py` stops re-zeroing that NaN for
   `median_hh_income` / `avg_hh_size` specifically in the join step (a third,
   necessary edit beyond the two originally scoped — the blanket
   `fillna(0.0)` in the per-column join loop was silently re-introducing the
   same defect one step downstream; those two ACS columns are the only ones
   where a present-but-NaN value is possible, since ACS covers every cell).
   Verified against the real Allegheny County run: 288 cells went from
   `median_hh_income == 0` to `NaN` (263 of them have real population, 14,942
   people), 0 cells now read exactly `$0`, and the 45 cells with a genuine
   Census estimate between $9.5k–$15k are byte-for-byte unchanged.
2. **`00_grid.py` couldn't rerun against a populated DB** — its `DELETE FROM
   geo_cells` ran outside the transaction that also deletes/reinserts, and
   `cell_features` FKs to it with no cascade. Collapsed into one
   `engine().begin()` block, `cell_features` deleted before `geo_cells`.
   Verified live: `STEP=00` now succeeds against the populated DB (18,275
   cells reloaded, `cell_features` correctly emptied pending the `STEP=12`
   rerun, all five key constraints intact afterward).
3. **`08_place_embeddings.py` aborted `make ingest` at step 08 for anyone
   without `GEMINI_API_KEY`** — `genai.Client()` was constructed
   unconditionally. Now constructed only when there's something to embed and
   a key exists; otherwise it prints the skip count and still emits the
   parquet from cache. Verified with the key unset (via `os.environ.pop`,
   not by touching `.env`) and `genai.Client` monkeypatched to raise if
   called — it did not get called.
4. **Two contract gaps** in `contracts/cell_features.md`: `dist_to_*_pct` is
   documented as inverted (100 = closest, not farthest — a scoring engine
   would otherwise double-invert it), and `source`/`resolution` are now
   labeled as static methodology maps, not per-row provenance (the row-level
   `rent_source`/`rent_resolution`/`rent_confidence`/`traffic_source` columns
   are authoritative for rent and traffic). Also noted: the parquet has no
   `updated_at`; only the DB table does.
5. This progress/tasks update.
6. `12_build_features.py` no longer emits a bare `float(r[d])` for
   `activity_by_daypart` (NaN now serializes to JSON `null`, matching the
   existing guard on `features`), and `traffic_source` defaults to `"proxy"`
   only when `activity_cells` was actually joined — not when the whole part
   is absent.
7. `sanity.py`'s `COLS` now watches `median_hh_income`; `_merge_chunks` in
   `01_census_acs.py` asserts the inner join doesn't drop rows.

**Tests added:** jam masking (`test_acs.py`), the area-weight per-column
denominator including the full-NaN case (`test_common.py`), the
`_merge_chunks` row-drop assertion (`test_acs.py`), the embeddings key-absent
path (`test_embeddings.py`), and the `traffic_source`/`activity_by_daypart`
absent-part and jam-NaN-survives-the-join cases (`test_build_features.py`).
68 tests pass (up from 61 — one bugfix cycle: the first area-weight fix
attempt referenced `out["_ia"]` before it was assigned; caught immediately by
running the new tests before committing), zero warnings, `ruff check .` clean.

**The partial-data reality, unchanged from Session 2 and confirmed still
true after these reruns:** `est_rent_psf_yr` is NaN for all 18,275 cells
(rent.parquet was never built — Task 13's data run is still deferred on the
manual rents collection); 900 of 15,295 places have a Gemini embedding
(daily quota hit mid-run); Google contributed to 175 of 15,295 places (95
matched + 80 Google-only) and to price-level data on about 2.6% of cells
(477 of 18,275) — the county-wide Google run is still deferred on GCP quota;
`traffic_source` is `"proxy"` for all 18,275 cells (BestTime real-traffic run
still pending user go-ahead).

**Pick up here next:** the data foundation is feature-complete and
internally consistent; nothing is blocked on code anymore. What's left is
entirely quota/key-and-money decisions the user owns: (a) collect 20–50
manual rents into `data/rents_manual.csv` to unblock Task 13's real run, (b)
decide whether/when to spend the Google Places budget for full county
coverage, (c) decide whether to let the Gemini embeddings job keep running
across multiple days against the daily quota, (d) decide whether to spend on
BestTime's real traffic. None of these require further code changes — the
scripts already degrade honestly (NaN/proxy) in their absence, and `make
ingest STEP=<n>` reruns cleanly once a decision unlocks a key. See
`.superpowers/sdd/2026-09-12-foundation-data-pipeline/final-fix-report.md`
for the full review-fix report.

## Dev 2

_Not yet started. Backend track, Phase 2 of `brain/tasks.md`._

## Dev 3

_Not yet started. Web track, Phase 3 of `brain/tasks.md`._
