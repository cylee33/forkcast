# Forkcast — Tasks

Checkbox state is the source of truth for what is built. Task numbers match
`docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`.

## Phase 0: Planning — complete

- [x] Brainstorm the product and confirm scope decisions
- [x] Write the spec `docs/superpowers/specs/2026-09-12-forkcast-design.md`
- [x] Write the foundation plan `docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`
- [x] Create the GitHub repo `cylee33/forkcast` and the `data/foundation` branch

## Phase 1: Foundation [P1] — in progress (8 of 16 tasks)

| # | Task | State | Commit |
|---|---|---|---|
| 1 | Repo skeleton, Docker DB, schema, CI | [x] done | `9aa27ab`, `df6b557` |
| 2 | Contracts + Pydantic/TypeScript mirrors | [x] done | `5e17f4d` |
| 3 | `brain/` team files + `.claude/agents` | [x] done | `f7f1e15` |
| 4 | `ingest/common.py` + `00_grid.py` | [x] done | `ea0fc68`, `e97b492` |
| 5 | `01_census_acs.py` | [x] code done, data blocked | `d2c6663` |
| 6 | `02_lodes.py` | [x] done | `47ce776` |
| 7 | `03_wprdc_food.py` + `cuisine_taxonomy.yaml` | [x] done | `a6a35c5`, `ef2ab38` |
| 8 | `04_osm_pois.py` (+ GTFS) | [x] done | `39c11e3`, `c1a0322` |
| 9 | `05_google_places.py` | [ ] | |
| 10 | `07_besttime.py` | [ ] | |
| 11 | `08_place_embeddings.py` | [ ] | |
| 12 | `09_spend_capacity.py` | [ ] | |
| 13 | `10_rent_proxy.py` + `rents_manual.csv` | [ ] | |
| 14 | `11_cuisine_affinity.py` | [ ] | |
| 15 | `12_build_features.py` | [ ] | |
| 16 | `sanity.py` + fixtures | [ ] | |

### Manual tasks for Dev 1, blocking the tasks named

- [ ] Get a free Census API key and put it in `.env` as `CENSUS_API_KEY` — blocks Task 5's data run, and Tasks 12 and 15 downstream
- [x] WPRDC food-facilities resource id found and set (`112a3821-334d-4f3f-ab40-4de1220b1a0a`)
- [ ] Provision `GOOGLE_PLACES_API_KEY` — blocks Tasks 9, 11 and 14. Estimated ~3,600 requests, about $117, inside Google's free monthly credit. Cuisine is identifiable for only 48% of open restaurants without it
- [ ] Provision `BESTTIME_API_KEY_PRIVATE` — blocks Task 10's real traffic (the proxy path still runs without it)
- [ ] Provision `VOYAGE_API_KEY` — blocks Task 11
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
