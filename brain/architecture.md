# Forkcast — Architecture

This is the blueprint for the product: the data-to-answer pipeline, the repo layout that implements it, the API surface, and who owns which piece. Copied from `forkcast-proposal.md` §2 and `docs/superpowers/specs/2026-09-12-forkcast-design.md` §2 and §4, plus the ownership table from `brain/team.md`.

## Pipeline

```
Concept text ──► Concept Parser (LLM → Restaurant DNA JSON, validated)
                        │
Center + radius ──► Candidate H3 cells (precomputed feature store)
                        │
                 Feature engineering per concept:
                   Demand (gravity catchment)   Competition (semantic, distance-decayed)
                   Traffic fit (daypart)         Access / Anchors
                   Spending fit                  Cost (rent efficiency)   Supply
                        │
                 Weighted Opportunity Score (weights from DNA, backend-validated)
                        │
                 Rank → merge adjacent high cells into zones → (stretch) match properties
                        │
                 Explainer (LLM narrates computed numbers only)
                        │
                 Map (hex heatmap + layer toggles) + ranked list + Why-Here + Compare
```

**Provider adapter rule:** scoring code never imports Google/Foursquare/BestTime/Census directly. Each source has an adapter in `providers/` writing to a common schema, so sources can be swapped for licensing or cost reasons without touching `scoring/`.

## Repo Layout

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

## Endpoints

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

## Ownership

| Track | Owner | Folders | Branch prefix |
|---|---|---|---|
| Foundation / data | Dev 1 (cylee) + Claude | `ingest/`, `contracts/`, `data/`, `brain/`, `.claude/`, `docker/` | `data/*` |
| Backend | Dev 2 | `api/`, `tests/test_api*.py`, `tests/test_scoring*.py` | `api/*` |
| Web | Dev 3 | `web/` | `web/*` |
