# Forkcast

**Describe the restaurant you want to open, and Forkcast searches an entire city for
the places where that exact concept has the strongest unmet demand — then explains
why.**

Most site-selection tools hand an entrepreneur a demographic map and leave them to
interpret it. Forkcast starts from the thing they actually know — the restaurant they
want to build — and turns that concept into a spatial search across demand,
competition, foot traffic, spending capacity, accessibility, suppliers and rent.

Demo market is Pittsburgh (Allegheny County). The architecture is any-US-metro, but
only Pittsburgh is precomputed.

> Forkcast is not financial or real-estate advice.

---

## Table of contents

- [How it works](#how-it-works)
- [The two modes](#the-two-modes)
- [Getting set up](#getting-set-up)
- [Repository layout](#repository-layout)
- [The data pipeline](#the-data-pipeline)
- [The scoring engine](#the-scoring-engine)
- [API](#api)
- [Contracts](#contracts)
- [Working on this project](#working-on-this-project)
- [Current status](#current-status)
- [Principles we hold to](#principles-we-hold-to)
- [Where to read more](#where-to-read-more)

---

## How it works

```
Concept text ──► Concept parser (LLM → Restaurant DNA JSON, schema-validated)
                        │
Center + radius ──► Candidate H3 cells (precomputed feature store)
                        │
                 Per-concept feature engineering:
                   Demand (gravity catchment)   Competition (semantic, distance-decayed)
                   Traffic fit (by daypart)     Access / anchors
                   Spending fit                 Cost (rent efficiency)   Suppliers
                        │
                 Weighted opportunity score (weights proposed by the LLM,
                 validated and renormalized by the backend)
                        │
                 Rank → merge adjacent high cells into zones
                        │
                 Explainer (LLM narrates only numbers the engine computed)
                        │
                 Map (hex heatmap + layer toggles) + ranked list + Why-Here + Compare
```

**The LLM never decides rankings.** It parses a concept into structure, proposes
weights the backend validates, and narrates numbers the engine computed. Every
ranking is deterministic, and every result stores the exact features and weights that
produced it.

The spatial unit is an [H3](https://h3geo.org/) resolution-9 cell, roughly 0.1 km²
and about 170 m across. Allegheny County takes 18,275 of them.

---

## The two modes

**Forward mode, for the entrepreneur.** *"I want to open X. Where, within R miles of
P, should I open it?"* Inputs are concept text, a center and a radius, optionally a
square-footage range and a monthly rent ceiling. Output is ranked opportunity zones
with sub-scores, an explanation, competitors, anchors, suppliers and risks.

**Reverse mode, for the landlord or the municipality.** *"I have a vacant storefront
here. What is this neighborhood missing?"* Roughly 100 concept archetypes run through
the same engine, and the ones with high demand and low relevant supply come back. It
is the seed of a two-sided marketplace.

**The question the engine answers.** Given this concept, where in this region is the
largest gap between potential customer demand and existing relevant supply, after
accounting for traffic, spending capacity, accessibility, suppliers and occupancy
cost?

---

## Getting set up

You need [Homebrew](https://brew.sh/) and about fifteen minutes.

```bash
git clone https://github.com/cylee33/forkcast && cd forkcast

# Toolchain. uv gives us Python 3.11; the pinned wheels do not build on newer ones.
brew install uv colima docker docker-compose
colima start --cpu 2 --memory 4       # Docker Desktop works too — nothing depends on which

make venv                             # .venv on Python 3.11 + requirements.txt
cp .env.example .env                  # then fill in the keys (see below)
make db-up                            # Postgres 16 + PostGIS + pgvector on :5432

make test && make lint                # both should be clean before you start
```

Confirm the database came up with all ten tables:

```bash
docker compose exec db psql -U forkcast -c "\dt"
```

**Working on the web track?** You need none of the above. Set
`NEXT_PUBLIC_USE_FIXTURE=1` and the app runs entirely off
`data/fixtures/recommend_sample.json` — no database, no keys, no backend. That
fixture arrives with foundation task 16; until then the web track builds against the
types in `web/lib/types.ts` and the schema in `contracts/recommend_response.json`.

### Keys

`.env` is gitignored; ask Dev 1 for the shared values.

| Variable | Needed by | Notes |
|---|---|---|
| `DATABASE_URL` | everything | Defaults to the compose database; usually leave it alone |
| `CENSUS_API_KEY` | `01_census_acs` | Free and instant. The API refuses keyless requests |
| `WPRDC_FOOD_RESOURCE_ID` | `03_wprdc_food` | Already known: `112a3821-334d-4f3f-ab40-4de1220b1a0a` |
| `GOOGLE_PLACES_API_KEY` | `05_google_places` | Roughly 3,600 requests for the county, about $117 |
| `BESTTIME_API_KEY_PRIVATE` | `07_besttime` | Optional. Without it the script writes its proxy |
| `GEMINI_API_KEY` | `08_place_embeddings` and the backend | Competitor-similarity embeddings, plus concept parsing, refinement and explanations |

---

## Repository layout

```
forkcast/
  brain/             project memory — read this first, every session
  contracts/         frozen interfaces between the three tracks
  data/
    raw/             gitignored source downloads and API caches
    processed/       parquet feature store, committed while it stays small
    fixtures/        sample cells and a sample response; always committed
  docker/db/         Postgres image and schema
  ingest/            the data pipeline, one numbered script per source
  api/               FastAPI service: scoring, parsing, explaining
  web/               Next.js app: map, leaderboard, chips, Why-Here
  tests/
  docs/superpowers/  the design spec and the implementation plans
```

### The `brain/` folder

Persistent project context, shared through git. Every developer's session reads it at
the start and updates it at the end.

| File | What it holds |
|---|---|
| `plan.md` | Decisions and the hour-by-hour build order |
| `tasks.md` | Every task with its state and the commit that closed it |
| `progress.md` | What is built, what blocks what, where to pick up. One section per developer |
| `lessons.md` | Struggles, surprises, and trial and error worth not repeating |
| `architecture.md` | The blueprint: pipeline, layout, endpoints, ownership |
| `team.md` | Ownership, setup, blockers, contract change log |
| `demo.md` | The three-minute demo script and its pre-flight checklist |

---

## The data pipeline

Every script under `ingest/` is idempotent and accepts `--limit N` for a smoke run,
reads from `data/raw/`, and writes a parquet to `data/processed/`. Seven of the twelve
also upsert Postgres; the rest produce per-cell inputs that `12_build_features` joins,
so `--no-db` is inert on those.

```bash
make ingest                       # everything, in order
make ingest STEP=04               # one step
make ingest STEP=04 ARGS="--limit 50 --no-db"
make sanity                       # static heatmaps to eyeball the feature store
make fixtures                     # regenerate data/fixtures/ from the real store
```

One caveat worth knowing before you run a single step: `STEP=00` rebuilds the grid, and
`cell_features` has a foreign key into it, so step 0 clears `cell_features` and step 12
repopulates it. A full `make ingest` handles that end to end. Running `make ingest
STEP=00` on its own leaves the table empty until you rerun `STEP=12`.

| Step | Source | What it produces |
|---|---|---|
| `00_grid` | Census TIGER | 18,275 H3 res-9 cells covering the county |
| `01_census_acs` | ACS 5-year 2023, block group | Population, households, income mix, age mix, families, vehicles, tenure, education, students |
| `02_lodes` | LODES WAC | Daytime workers and higher-wage workers |
| `03_wprdc_food` | WPRDC food facilities | The authoritative restaurant list, with operational status |
| `04_osm_pois` | OpenStreetMap + PRT GTFS | Anchors, suppliers, parking, walkability, road frontage, transit trips |
| `05_google_places` | Google Places (New) | Ratings, review counts, price level, business status, place types |
| `07_besttime` | BestTime, or a proxy | Relative busyness by daypart |
| `08_place_embeddings` | Gemini `gemini-embedding-001` | A 1024-dimension vector per place, for competitor similarity |
| `09_spend_capacity` | BLS CEX × ACS | Spending capacity and the local price-tier profile |
| `10_rent_proxy` | Zillow ZORI + hand-collected asking rents | An estimated rent per square foot, always labeled an estimate |
| `11_cuisine_affinity` | derived | Observed affinity per cuisine |
| `12_build_features` | all of the above | `cell_features`: every column plus its metro-wide percentile |

Each feature carries its `source` and `resolution`, and the `cell_features` table
carries an `updated_at`, so the confidence score and the interface can both be honest
about a ZIP-level number sitting inside a 170-metre hexagon. Two details to know before
you read those columns, both spelled out in `contracts/cell_features.md`:

- **`dist_to_*_pct` is inverted** — 100 means closest, not farthest. A scoring engine
  that applies the natural "distance is bad, so invert the percentile" will invert
  twice and get Access and Suppliers exactly backwards.
- **`source` and `resolution` are methodology labels, not per-row provenance.** For
  rent and traffic the per-row columns win: `rent_source`, `rent_resolution`,
  `rent_confidence` and `traffic_source`. The parquet has no `updated_at`; only the
  database table does.

### Provider adapters

Scoring code never imports Google, Foursquare, BestTime or Census directly. Each
source gets an adapter that writes a common schema, so a source can be swapped for
licensing or cost reasons without touching `scoring/`.

---

## The scoring engine

Seven sub-scores, each on a 0–100 metro-wide percentile, combined by concept-specific
weights.

| | Sub-score | What it measures |
|---|---|---|
| **D** | Demand | A gravity catchment: nearby population weighted by daypart, customer fit and spending fit, decayed by travel time |
| **C** | Competition | Semantic similarity to existing places, weighted by their popularity and decayed by distance |
| **T** | Traffic fit | Activity during the dayparts this concept actually cares about |
| **A** | Access | Walkability, transit, parking and visibility, weighted by the concept's stated priorities |
| **S_spend** | Spending fit | Local capacity, matched to the concept's price tier — it peaks at a match, not at the richest |
| **K** | Cost | Affordable rent against estimated rent |
| **Sup** | Suppliers | Distance to the supplier types the concept needs |

**Competition is semantic, not categorical.** Every place is embedded, and a concept
is compared against those vectors. A Neapolitan pizzeria scores 0.96 against another
Neapolitan place, 0.71 against generic Italian, 0.58 against Domino's and 0.08
against Thai. Complementary businesses count toward a clustering bonus rather than
against the score.

**Weights are proposed, then policed.** The parser suggests weights; the backend
asserts each is between 0 and 1, clamps any single weight at 0.4, renormalizes, and
stores the final set alongside the analysis. Defaults exist per service format, so a
ghost kitchen weights demand and rent heavily and ignores foot traffic, while a cafe
leans on traffic and access.

**Confidence travels with every score.** It blends data completeness, freshness, rent
confidence, whether traffic is real or proxied, and how many places sit nearby. The
interface shows it next to the number: *Opportunity 91 · Confidence 63%*.

**The backtest keeps us honest.** For every open place with at least 30 reviews, we
build a profile from its cuisine and price tier, score its own cell, and compute a
Spearman correlation against its review count. That number is in the footer. It is a
survivorship-biased proxy and we say so.

---

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/concept/parse` | Concept text → a validated `ConceptProfile` |
| POST | `/api/concept/refine` | A profile plus an instruction → a patched profile and a field diff |
| POST | `/api/analysis` | Profile, center, radius → a `RecommendResponse` |
| GET | `/api/analysis/{id}` | Replay a stored analysis, for shareable links |
| POST | `/api/explain` | A profile and a zone → the Why-Here narrative |
| POST | `/api/compare` | Up to three zones → one paragraph on the trade-off |
| POST | `/api/reverse` | A point → the top eight concepts for it |
| GET | `/api/meta` | Backtest correlation, data freshness, model names |

Scoring runs in NumPy over an in-memory copy of the feature store, not in SQL. The
whole county is about 18,000 cells and 15,000 places, so a request filters
candidates, computes vectorized sub-scores, weights, ranks and merges zones in well
under a second.

---

## Contracts

`contracts/` is the seam between the three tracks and is **frozen after the
foundation phase**.

| File | What it defines |
|---|---|
| `concept_profile.json` | The Restaurant DNA the parser must produce |
| `recommend_response.json` | Exactly what `/api/analysis` returns |
| `cell_features.md` | Every column the feature store must carry, with units and provenance |
| `places.md` | The `places` table |

`api/models.py` and `web/lib/types.ts` mirror these. Backend tests validate real
responses against the JSON Schema, so the schema is the authority and the mirrors are
conveniences.

To change a contract: edit it, add a row to the change log in `brain/team.md`, and
tell the team. Do not change one quietly — two other people are building against it.

---

## Working on this project

### Who owns what

| Track | Owner | Folders | Branch prefix |
|---|---|---|---|
| Foundation and data | Dev 1 | `ingest/`, `contracts/`, `data/`, `brain/`, `docker/` | `data/*` |
| Backend | Dev 2 | `api/`, its tests | `api/*` |
| Web | Dev 3 | `web/` | `web/*` |

Ownership is drawn along folder lines so three people can work at once without
fighting over merges.

### Rules

- Commit after every completed task. Rebase on `main` before merging. Never
  force-push `main`.
- Small pull requests, self-merged once CI is green. A second pair of eyes is
  required only for a change to `contracts/`.
- Update only your own section of `brain/progress.md`, so the file never conflicts.
- `data/raw/` is gitignored and large — never try to share it. `data/processed/`
  rides along in the repo while it stays under 50 MB.

### Tests

```bash
make test                        # pytest
make lint                        # ruff
.venv/bin/python -m pytest -q -W error   # what CI effectively enforces
```

Test output should be pristine. A warning is a finding, not noise. Continuous
integration runs ruff and pytest on every push and pull request.

---

## Current status

Foundation phase complete — all sixteen tasks. Sixty-eight tests pass, lint is clean,
and the sanity run reports one known gap.

| Built | Rows |
|---|---|
| `geo_cells` — the H3 grid | 18,275 |
| `acs` — demographics, income and age mix | 18,275 cells × 20 columns |
| `lodes` — daytime workers | 18,267 cells, 686,253 workers |
| `osm_cells` — anchors, access, suppliers, transit | 18,275 cells × 30 columns |
| `places` — WPRDC food facilities merged with Google | 15,295, of which 10,050 are open |
| `place_embeddings` — competitor similarity vectors | 900 of 15,295 places |
| `activity_cells` — daypart activity | 18,275 cells, all `traffic_source = proxy` |
| `spend` — spending capacity and local price mix | 18,275 cells |
| `affinity` — observed cuisine affinity | 18,275 cells × 49 cuisines |
| `suppliers` | 242, including 5 hand-listed wholesalers |
| **`cell_features` — the handoff artifact** | **18,275 cells × 132 columns** |

The features check out against geography we can verify by eye. Downtown leads
walkability and transit, the South Side has the most bars, Oakland has the
universities, the outer suburbs are empty, and supplier distances run from 340 metres
in the Strip District to 22 kilometres in Sewickley.

### What is partial, and why that is written down rather than filled in

Three external quotas ran out mid-build. Nothing was fabricated to cover for them —
where a value is unknown it is `NULL`, never a plausible-looking number, and the
per-row `source`, `rent_source` and `traffic_source` columns say which is which.

| Gap | State | What lifts it |
|---|---|---|
| Rent | `est_rent_psf_yr` is NULL on every cell | 20–50 hand-collected asking rents in `data/rents_manual.csv` |
| Google Places | Reached ~4% of the county; cuisine identified for 48.6% of open places, 3 Korean | A billing account on the Cloud project, then `make ingest STEP=05` |
| Embeddings | 900 of 15,295 places | Gemini's daily quota resetting, then `make ingest STEP=08` |
| Foot traffic | Proxy everywhere; all 58 BestTime responses came back `null` | Understanding the null responses before spending more |
| Census | 288 cells have no income estimate | Nothing — the Census itself cannot estimate them |

The Cost sub-score should run at weight 0 and renormalise until rents arrive, which the
cut order already anticipates. Everything else degrades rather than blocks.

`brain/tasks.md` has the per-task state and `brain/progress.md` has the detail.

---

## Principles we hold to

**Cuisine affinity is observed, never ethnic.** We do not model "many Korean
residents, therefore a Korean restaurant will do well." It is statistically weak and
it reads as demographic steering. Affinity is built only from revealed behavior: how
engaged the existing restaurants of that cuisine are nearby, how engaged complementary
cuisines are, and whether the local price mix fits. Census ancestry and foreign-born
tables are not ingested at all. Demographics describe a market — age, income,
families, students, vehicles — but they never stand in for taste.

**No false precision.** Scores come with buckets, sub-scores and a confidence figure.
There is no "expected annual profit: $413,287." Any revenue figure is a labeled
scenario with its assumptions on screen.

**Closed restaurants do not count as competition.** We filter on WPRDC operational
status and Google's business status. A neighborhood full of shuttered restaurants is
an opportunity signal or a warning, never a crowded market.

**Survivorship bias is real and we say so.** Existing restaurants are the ones that
survived. The backtest measures what survivors look like, not what causes success.

**Foot traffic is relative.** BestTime reports a venue's busyness as a share of its
own weekly peak. We never convert that into visitor counts.

**Licensing is respected.** No scraping of Google Maps, Yelp, LoopNet or Crexi. The
provider adapters exist so compliant swaps stay possible.

---

## Where to read more

| Document | What it is for |
|---|---|
| `brain/progress.md` | Where the work stands and where to pick it up |
| `brain/architecture.md` | The blueprint: pipeline, layout, endpoints, ownership |
| `brain/lessons.md` | What already went wrong, so it does not go wrong again |
| `docs/superpowers/specs/2026-09-12-forkcast-design.md` | The design spec and every scope decision |
| `docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md` | The foundation phase, task by task |
| `forkcast-proposal.md` | The original proposal, including the scoring formulas in full |
| `CLAUDE.md` | How AI coding sessions work in this repository |
