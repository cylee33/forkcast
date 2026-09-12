# Forkcast — Tasks

Checkbox state is the source of truth for what is built. Task numbers match
`docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`.

## Optional Yelp popularity integration [ML]

- [x] Branch from updated `origin/main` at `f72f19c`
- [x] Add contract-neutral `score_profile(profile, h3_ids)` adapter
- [x] Broadcast matched ACS 2021 tract inputs to all 18,275 Pittsburgh H3 centers
- [x] Keep Yelp-trained model, derived lookup, and evaluation metadata local/ignored
- [x] Verify metro-fixed percentiles, coverage flags, portable model predictions, tests, and lint
- [x] Add a contract-compatible helper that enriches GeoJSON cell properties when local artifacts exist
- [x] Add a standalone FastAPI route for local end-to-end model testing
- [ ] Call the helper from `/api/analysis` after the backend endpoint lands
- [ ] Resolve Yelp review/approval requirements before any public model/results release

## Phase 0: Planning — complete

- [x] Brainstorm the product and confirm scope decisions
- [x] Write the spec `docs/superpowers/specs/2026-09-12-forkcast-design.md`
- [x] Write the foundation plan `docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`
- [x] Create the GitHub repo `cylee33/forkcast` and the `data/foundation` branch

## Phase 1: Foundation [P1] — complete (16 of 16 tasks)

| # | Task | State | Commit |
|---|---|---|---|
| 1 | Repo skeleton, Docker DB, schema, CI | [x] done | `9aa27ab`, `df6b557` |
| 2 | Contracts + Pydantic/TypeScript mirrors | [x] done | `5e17f4d` |
| 3 | `brain/` team files + `.claude/agents` | [x] done | `f7f1e15` |
| 4 | `ingest/common.py` + `00_grid.py` | [x] done | `ea0fc68`, `e97b492` |
| 5 | `01_census_acs.py` | [x] done, acs.parquet loaded | `d2c6663`, `3d09c06` |
| 6 | `02_lodes.py` | [x] done | `47ce776` |
| 7 | `03_wprdc_food.py` + `cuisine_taxonomy.yaml` | [x] done | `a6a35c5`, `ef2ab38` |
| 8 | `04_osm_pois.py` (+ GTFS) | [x] done | `39c11e3`, `c1a0322` |
| 9 | `05_google_places.py` | [x] code done, county run deferred on GCP quota | `b0417c4`, `c0c333d`, `9807ed2` |
| 10 | `07_besttime.py` | [x] code done, proxy path run; real traffic pending user go-ahead | `ff90346` |
| 11 | `08_place_embeddings.py` | [x] code done, 900/15,295 embedded (Gemini daily quota) | `a74f5b1`, `7a82853` |
| 12 | `09_spend_capacity.py` | [x] done | `2f68c84` |
| 13 | `10_rent_proxy.py` + `rents_manual.csv` | [x] code done, data run deferred on manual rents | `e651792`, `93b4179`, `00aad69` |
| 14 | `11_cuisine_affinity.py` | [x] done (pct floor fixed in `98b3da1`) | `5d155bb`, `98b3da1` |
| 15 | `12_build_features.py` | [x] done — cell_features 18,275 x 132 | `d5e1441`, `4a52a24` |
| 16 | `sanity.py` + fixtures | [x] done | `ea322f7`, `d1c87a0` |

### Manual tasks for Dev 1, blocking the tasks named

- [x] Census API key obtained and set in `.env` as `CENSUS_API_KEY` — unblocks Task 5's data run, and Tasks 12 and 15 downstream
- [x] WPRDC food-facilities resource id found and set (`112a3821-334d-4f3f-ab40-4de1220b1a0a`)
- [x] `GOOGLE_PLACES_API_KEY` provisioned and set in `.env` — unblocks Tasks 9, 11 and 14. Estimated ~3,600 requests, about $117, inside Google's free monthly credit. Cuisine is identifiable for only 48% of open restaurants without it
- [ ] Provision `BESTTIME_API_KEY_PRIVATE` — blocks Task 10's real traffic (the proxy path still runs without it)
- [x] `GEMINI_API_KEY` provisioned and set in `.env` — Task 11 ran against it (900/15,295 embedded before the daily quota hit); the key is now quota-exhausted, so Phase 2's LLM calls (parse, refine, explain) remain blocked on quota resetting or a new key, not on provisioning
- [ ] Hand-collect 20–50 asking rents into `data/rents_manual.csv` — blocks Task 13
- [x] Wholesale suppliers hand-listed in `data/suppliers_manual.csv` (5 of 6; US Foods omitted, address unverifiable)

## Phase 2: Backend [P2] — plan written after foundation

- [ ] Scoring modules (`demand, competition, traffic, access, spending, cost, supply`)
- [ ] Weight validator and `analyses` persistence
- [ ] Zones (connected components, neighborhood names)
- [ ] Concept parser, refine, explainer
- [ ] Reverse mode + `concept_archetypes.yaml`
- [ ] Backtest (Spearman ρ)
- [ ] Endpoints and `contracts/` validation tests

## Phase 3: Web [P3] — plan written after foundation

- [ ] Skeleton running on `data/fixtures/recommend_sample.json`
- [ ] Map, hex layer, layer toggles
- [ ] Leaderboard, profile chips, refine bar
- [ ] Why-Here panel, competitor panel
- [ ] Reverse-mode UI

## Phase 4: Integration [P1]

- [ ] Hour-10 checkpoint: all three developers on `main`, Korean street-food concept end-to-end
- [ ] Freeze `contracts/`
- [ ] Backtest ρ in the footer
- [ ] Weight tuning
- [ ] Bug bash against `brain/demo.md`
- [ ] Demo rehearsal
