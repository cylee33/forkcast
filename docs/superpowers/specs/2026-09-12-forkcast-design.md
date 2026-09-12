# Forkcast — Design Spec (v1, hackathon)

**Date:** 2026-09-12
**Source:** `forkcast-proposal.md` (v2, US-only). This spec records the decisions made on top of that proposal. Where this spec is silent, the proposal governs.

---

## 1. Decisions

| # | Decision |
|---|---|
| D1 | Real 24-hour hackathon. Three developers. Strict cut order applies. |
| D2 | **Foundation phase** (Dev 1 + Claude) delivers the full Track A data pipeline before the other two developers join. If foundation finishes early, Dev 1 + Claude continue into backend (Dev 2 scope) and then web (Dev 3 scope). |
| D3 | Everyone runs their own Claude Code session off the shared `brain/` and `.claude/` folders. Only Dev 1 runs the foundation session. |
| D4 | No sponsor-mandated stack or LLM provider. Paid APIs are chosen by feature need, not budget. |
| D5 | **Core scope:** concept parser + editable chips, refine bar, scoring engine, hex map + layer toggles, zone leaderboard, Why-Here explainer, backtest ρ in footer, **reverse mode**. |
| D6 | **Stretch (only after hour 16):** compare table, report modal. |
| D7 | **Cut:** properties (PropertyProvider, curated CSV). Foursquare unless OSM anchor coverage is thin. |
| D8 | Pittsburgh / Allegheny County only. Any-US center is out. |
| D9 | Model: §5.10 option 0 (hand-weighted, LLM-proposed weights validated by backend). Option 1 (learned weights) only if hours 10–13 are free. |
| D10 | Demo runs from a laptop via `docker-compose`. Vercel/Render deploy is stretch. |
| D11 | Local Postgres (PostGIS + pgvector image) in compose. Not Supabase. |
| D12 | LLM: `claude-sonnet-5` for parse, refine, explain, compare. Embeddings: Voyage `voyage-3`. Recorded in `analyses.model_json`. |
| D13 | Git repo is created and pushed as **task 1** of foundation. Commit after every completed task. |

---

## 2. Repo layout and contracts

Layout follows proposal §2.1 with these additions:

```
forkcast/
  brain/                    # shared project memory (plan, tasks, progress, lessons, architecture, team, demo)
  .claude/
    CLAUDE.md               # session rules (existing)
    agents/                 # data-ingest.md, backend.md, frontend.md, qa.md
  contracts/                # frozen at end of foundation
    concept_profile.json    # JSON Schema for ConceptProfile (proposal §4)
    cell_features.md        # every column: name, unit, source, resolution, updated_at semantics
    recommend_response.json # JSON Schema for RecommendResponse (proposal §5.11)
    places.md               # places table columns (proposal §3.3)
  docs/superpowers/specs/   # this spec
  data/
    raw/                    # gitignored
    processed/              # parquet outputs; committed if < 50 MB total, else zip + `make restore-data`
    fixtures/               # always committed: cell_features_sample.parquet (~200 real cells around Oakland), recommend_sample.json
  ingest/                   # proposal §2.1
  api/                      # proposal §2.1 minus properties
  web/                      # proposal §2.1 minus PropertyCard
  tests/
  docker-compose.yml        # db (postgis+pgvector), api, web
  Makefile                  # ingest, ingest STEP=NN, backtest, restore-data, test
  .env.example              # every key listed
```

`api/models.py` (Pydantic) and `web/lib/types.ts` mirror `contracts/`. A change to `contracts/` after freeze requires a note in `brain/team.md` and a message to the team.

---

## 3. Data pipeline (foundation scope)

Every `ingest/NN_*.py` is idempotent: reads `data/raw/`, writes `data/processed/*.parquet`, upserts the DB. Each accepts `--limit N` for smoke runs. `make ingest` runs all in order; `make ingest STEP=03` runs one.

| Step | Source | Decision |
|---|---|---|
| `00_grid` | Census TIGER county polygon | H3 res 9 → `geo_cells`. ~7k cells. |
| `01_census_acs` | Census API, ACS 5-yr 2023, block group | Cached JSON. Area-weighted to cells. No ancestry / foreign-born tables. |
| `02_lodes` | LODES WAC | Block → cell by area weight. `workers_daytime`, `workers_high_wage`. |
| `03_wprdc_food` | WPRDC Allegheny County Food Facilities | Authoritative `places` base rows. `is_open` from operational status. |
| `04_osm_pois` | Geofabrik PA extract | Anchors, transit stops, parking, suppliers, F&B. Plus GTFS (PRT) for `transit_daily_trips`. |
| `05_google_places` | Google Places Nearby Search + Details, field-masked | County-wide grid of requests, cached raw JSON, matched to WPRDC rows by name + distance. Adds `rating, reviews, price_level, business_status`. Never per-hex calls. |
| `06_foursquare` | Foursquare Places | **Skipped** unless sanity heatmap shows thin anchor coverage. |
| `07_besttime` | BestTime forecasts | Top ~500 POIs by review count. Proxy elsewhere (anchors + transit + workers + POI density). `traffic_source = real | proxy` per cell. |
| `08_place_embeddings` | Voyage `voyage-3` | `name + categories + editorial summary` → pgvector(1024). |
| `09_spend_capacity` | BLS CEX × ACS income brackets, Google `price_level` | `spending_capacity`, `local_price_profile{1..4}`. |
| `10_rent_proxy` | Zillow ZORI (ZIP), assessor land value, `data/raw/rents_manual.csv` (20–50 hand-collected asking rents) | Regression → `est_rent_psf_yr`, `rent_confidence`, `rent_source`, `rent_resolution`. Always labeled estimate. |
| `11_cuisine_affinity` | Derived from `places` | Proposal §3.4 observed affinity only. |
| `12_build_features` | All above | Join, `grid_disk(1)` smoothing for point counts, metro-wide percentiles (`*_pct`), write `cell_features` table + parquet. Every row carries `source, resolution, updated_at`. |
| `sanity.py` | `cell_features` | Static PNG heatmaps of pop, workers, POI density, rent. Oakland / Downtown / Strip should be hot. |

---

## 4. Scoring engine and API

FastAPI, single process. On startup, load `cell_features`, `places`, and embeddings into memory (pandas + NumPy). Per request: candidate cells by H3 distance within radius plus `grid_disk(3)` halo, compute sub-scores vectorized, weight, rank, merge zones. Target < 1 s.

- **`scoring/*.py`**: one pure function per sub-score, `(features_df, profile, params) -> np.ndarray` in 0–100. Formulas as proposal §5.2–5.4.
- **`scoring/weights.py`**: proposal §5.5 defaults by service format. Validate LLM `proposed_weights`: assert 0 ≤ w ≤ 1, clamp any single weight ≤ 0.4, renormalize. Final weights stored in `analyses.weights_json`.
- **`services/zones.py`**: top-decile cells → H3 connected components → rank by max cell → neighborhood name via Nominatim reverse geocode (cached in DB).
- **`services/concept_parser.py`**: `claude-sonnet-5` with tool-use whose input schema is `ConceptProfile`. One retry on Pydantic failure. Cache by normalized text in `concept_cache` table. Three golden tests on the demo concepts.
- **`services/refine.py`**: same model. Input profile + instruction → patched profile. Return the field diff for the UI.
- **`services/explainer.py`**: `claude-sonnet-5`. Receives only computed sub-scores, named competitors, anchors, rent estimate. Prompt forbids new numbers. Called lazily on zone click.
- **Reverse mode**: `concept_archetypes.yaml` (~100 rows). Build a profile per archetype, score cells within 1 km of the pin, rank by total with `+15 if gap_flag`, return top 8 with sub-scores.
- **Backtest**: `api/backtest.py` (`make backtest`). For every open place with ≥ 30 reviews, build profile from cuisine + price level, score its own cell, Spearman ρ vs `log(reviews)`. Writes ρ and N to `backtest_results`. Never cut.
- **Persistence**: `analyses` + `analysis_cells` per run for shareable URLs.

Endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/concept/parse` | text → `ConceptProfile` |
| POST | `/api/concept/refine` | profile + instruction → patched profile + diff |
| POST | `/api/analysis` | profile + center + radius (+ rent ceiling) → `RecommendResponse` |
| GET | `/api/analysis/{id}` | replay a stored analysis |
| POST | `/api/explain` | profile + zone → Why-Here text |
| POST | `/api/compare` | up to 3 zones → trade-off paragraph (stretch) |
| POST | `/api/reverse` | lat, lng (+ sqft, rent) → top 8 concepts |
| GET | `/api/meta` | backtest ρ, N, data freshness, model names |

---

## 5. Web

Next.js 14 app router, TypeScript, Tailwind, MapLibre GL. One page.

- **State**: a single `useAnalysis` hook holds profile, weights, cells GeoJSON, zones, selected zone, active layer, mode (forward / reverse). No global store library.
- **API client**: `web/lib/api.ts`, typed from `contracts/`. `NEXT_PUBLIC_API_URL`. With `NEXT_PUBLIC_USE_FIXTURE=1` it serves `data/fixtures/recommend_sample.json`, so the web track works with no backend.
- **Map**: free basemap (OpenFreeMap or MapTiler key). Hex layer is a GeoJSON fill, colored by the active layer's property in 5 quantile buckets computed within the radius. Numbered zone markers. Draggable pin + radius slider.
- **Layers**: Opportunity, Demand, Competition, Traffic, Spending, Rent, Suppliers, Transit. Each maps to one cell property; toggling swaps the `fill-color` expression only.
- **Components**: `ConceptBar` (input + 3 example chips), `ProfileChips` (editable; edits rerun analysis; clarifying-question chips when `confidence < 0.5`), `RefineBar`, `MapView`, `LayerControls`, `Leaderboard` (zones with 7 mini sub-score bars, confidence, gap badge, rent estimate), `WhyHere` (lazy `/api/explain`), `CompetitorPanel` (direct vs indirect, White-Space bars), `ReverseMode` (pin → concept cards). Stretch: `CompareTable`, `ReportModal`.
- **Loading**: stepped status line ("Parsing concept → Scoring N cells → Merging zones → Done").
- **Share**: `/?a={analysis_id}` loads `GET /api/analysis/{id}`.
- **Footer**: "Backtested against N open Pittsburgh restaurants, ρ = 0.xx" from `/api/meta`, plus one-line not-financial-advice disclaimer.

---

## 6. Team workflow

### Ownership

| Track | Owner | Folders |
|---|---|---|
| Foundation / data | Dev 1 + Claude | `ingest/`, `contracts/`, `data/`, `brain/`, `.claude/`, compose |
| Backend | Dev 2 | `api/`, `tests/` |
| Web | Dev 3 | `web/` |
| After handoff | Dev 1 + Claude | backtest, weight tuning, confidence score, late-arriving BestTime / rent hot-swap, integration bug bash, demo script, README |

If foundation finishes early, Dev 1 + Claude start backend, then web, and hand off whatever is in progress when Dev 2 / Dev 3 join.

### Git

- GitHub repo, created and pushed before any code. `main` is never force-pushed.
- Branch per track: `data/*`, `api/*`, `web/*`. Small PRs. Self-merge after CI is green; a second look is required only for PRs touching `contracts/`.
- Rebase on `main` before merge. Commit after every completed task.
- CI (GitHub Actions, < 2 min): `pytest tests/` + `ruff` for `api/` and `ingest/`; `tsc --noEmit` + `eslint` for `web/`.

### Shared `brain/`

| File | Rule |
|---|---|
| `plan.md`, `architecture.md` | Derived from this spec. Stable. |
| `tasks.md` | Phases with checkboxes; each task tagged `[P1]`, `[P2]`, or `[P3]`. |
| `team.md` | Ownership table, hour-10 checkpoint status, blockers, contract change log. Each dev edits their own row. |
| `progress.md` | One section per dev, append-only, own section only (avoids merge conflicts). |
| `lessons.md` | Append-only. |
| `demo.md` | 3-minute demo script and manual pre-demo checklist. |

`.claude/CLAUDE.md` session-start and session-end rules apply to every developer's session, so `brain/` stays current and committed.

### Secrets and data

- `.env` gitignored; keys shared once out-of-band; `.env.example` is complete.
- `data/raw/` gitignored. `data/processed/` committed if under 50 MB total, otherwise distributed as one zip via `make restore-data`. `data/fixtures/` always committed.

### Hour-10 checkpoint

All three developers on `main`, `docker-compose up`, Korean street-food concept runs end-to-end. Freeze `contracts/`.

### Cut order if behind

compare table → report modal → rent (K shows n/a, weight 0, renormalize) → BestTime (proxy only). **Never cut:** editable chips, refine bar, backtest, layer toggles, reverse mode.

---

## 7. Testing and error handling

| Area | Test |
|---|---|
| Ingest | `tests/test_ingest_smoke.py`: grid + `build_features` on a fixture raw sample. Assert row counts, no NaN in required columns, percentiles within 0–100. Every script supports `--limit N`. |
| Scoring | `tests/test_scoring.py`: each sub-score module on the fixture parquet. Golden: the three demo concepts must produce different #1 zones. Weight validator: clamp and renormalize cases. `tests/test_competition.py`: similarity threshold, closed places excluded. |
| Parser | `tests/test_concept_parser.py`: three golden concepts using recorded LLM responses (JSON cassettes) so CI needs no API key. Live calls only with `RUN_LIVE=1`. |
| API | `tests/test_api.py`: FastAPI TestClient on a fixture DB. `/api/analysis` output validates against `contracts/recommend_response.json`. |
| Web | `tsc` + eslint only. Manual checklist in `brain/demo.md`. |
| Backtest | `make backtest` prints ρ and N and writes them to the DB. Never cut. |

Error handling:

- Parser schema failure → one retry → `422` carrying `clarifying_questions`.
- LLM unavailable → parser falls back to keyword match against `cuisine_taxonomy.yaml`, returns low confidence, chips remain editable.
- Explainer failure → UI shows sub-scores only, no narrative.
- Missing feature column → confidence drops for affected cells; never a crash.
- Rent absent → K displayed as n/a, K weight set to 0, remaining weights renormalized.

---

## 8. Demo

Proposal §9, unchanged, minus properties. Reverse mode is step 4.
