# Forkcast — AI Restaurant Site Selection (v2, US-only)

**One-line pitch:** Describe the restaurant you want to build, and Forkcast analyzes an entire city to find where that exact concept has the strongest unmet demand — then explains why.

**Positioning (for the pitch deck):** Existing tools ask the entrepreneur to interpret demographic maps and market reports themselves. Forkcast starts with what they actually know — the restaurant they want to open — and turns that concept into a spatial search across demand, competition, foot traffic, spending capacity, accessibility, suppliers, and rent.

This document is a build spec for an AI coding agent. §0 fixes assumptions, §1–7 define architecture/data/scoring/API, §8 is the 24-hour build order, §9 the demo, §10 open questions, §11 stretch features and risks.

---

## 0. Working assumptions (confirmed unless marked)

| # | Assumption |
|---|---|
| A1 | **Hackathon: ~24 hours, team of 2–4.** Vertical slice by hour ~10; §8 has a strict cut order. |
| A2 | **US only. Demo market: Pittsburgh / Allegheny County.** Architecture is any-US-metro (Census + national POI providers), but only Pittsburgh is precomputed. No non-US data sources anywhere. |
| A3 | **Spatial unit: H3 res 9** (~0.1 km², ~170 m edge). Fall back to res 8 if sparse. |
| A4 | **Stack:** Next.js 14 + TypeScript + Tailwind + MapLibre GL; FastAPI + Python; PostgreSQL + PostGIS + pgvector (Supabase acceptable); Claude API for parsing/explanation; any embedding API (Voyage/OpenAI) for competitor similarity. Deploy: Vercel + Render/Fly. |
| A5 | **Sponsor/data grant confirmed.** Spend on, in order: (1) Google Places API (field-masked) for competitor rating/price/status county-wide; (2) BestTime API for relative hourly busyness of POIs; (3) Foursquare Places for broader POI/anchor coverage; (4) a small commercial-rent pull if a sponsor can supply one. Proxies in §3 are the fallback for anything not in hand by hour 6. |
| A6 | **No accounts in v1.** Shareable result URLs. |
| A7 | **The LLM never decides rankings.** It parses concepts into structure, proposes weights the backend validates, and narrates numbers the engine computed. All ranking is deterministic and every result stores the exact features and weights that produced it. |

---

## 1. Purpose and users

**Forward mode (entrepreneur):** "I want to open *X*. Where, within *R* miles of *P*, should I open it?" Inputs: concept text, center, radius; optional sqft range and monthly rent ceiling. Output: ranked opportunity zones with sub-scores, explanation, competitors, anchors, suppliers, risks, and (stretch) matching properties.

**Reverse mode (landlord / municipality):** "I have a vacant storefront here. What is this neighborhood missing?" Runs ~100 concept archetypes through the same engine and returns those with high demand and low relevant supply. This is the seed of a two-sided marketplace.

**The question the engine answers:** *Given this concept, where in this region is the largest gap between potential customer demand and existing relevant supply, after accounting for traffic, spending capacity, accessibility, suppliers, and occupancy cost?*

---

## 2. Architecture

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

### 2.1 Repository layout

```
forkcast/
  docker-compose.yml                # postgres+postgis+pgvector, api, web
  data/  raw/ (gitignored)  processed/  cell_features.parquet  places.parquet  fixtures/
  ingest/
    00_grid.py                      # H3 cells for Allegheny County
    01_census_acs.py                # block groups → cells
    02_lodes.py                     # daytime workers
    03_wprdc_food.py                # WPRDC food-facility dataset (operational status!)
    04_osm_pois.py                  # Overpass/Geofabrik: F&B, supply, anchors, transit, parking
    05_google_places.py             # rating / reviews / price / business_status (field-masked)
    06_foursquare.py                # optional broader POI + chain flags
    07_besttime.py                  # relative hourly busyness per POI → cell daypart activity
    08_place_embeddings.py          # embed every place (name+categories+summary) → pgvector
    09_spend_capacity.py            # CEX + ACS income → spending capacity + price-tier profile
    10_rent_proxy.py                # ZORI + hand-collected asking rents → regression
    11_cuisine_affinity.py          # OBSERVED cuisine affinity (see §3.4)
    12_build_features.py            # join, normalize, percentile, write cell_features
    cuisine_taxonomy.yaml
    concept_archetypes.yaml         # ~100 archetypes for reverse mode
  api/
    main.py  models.py  db.py
    routers/ concept.py analysis.py cells.py properties.py reverse.py
    services/ concept_parser.py scoring_engine.py explainer.py zones.py
    providers/ census.py wprdc.py osm.py google_places.py foursquare.py besttime.py
               property_provider.py (real API | CSV | demo dataset behind one interface)
    scoring/ demand.py competition.py traffic.py access.py spending.py cost.py supply.py normalize.py
    prompts/ concept_parser.md explainer.md refine.md
  web/
    app/page.tsx
    components/ ConceptBar RefineBar MapView HexLayer LayerControls Leaderboard
                ScoreCard WhyHere CompetitorPanel CompareTable PropertyCard ReportModal
    lib/api.ts
  tests/ test_scoring.py test_concept_parser.py test_competition.py
```

---

## 3. Data layer (Pittsburgh)

### 3.1 Grid
`00_grid.py`: `h3.polygon_to_cells(allegheny_county, 9)` → ~7k cells with centroid and hex polygon in PostGIS. Polygon sources are area-weighted onto cells; point sources are counted per cell with `grid_disk(1)` smoothing where noted.

### 3.2 Sources

| Feature group | Source | Cell features | Notes |
|---|---|---|---|
| Resident demographics | **Census ACS 5-yr (2023), block group** | `pop_total, hh_count, median_hh_income, income_distribution[brackets], pct_age_18_24/25_34/35_54/55p, pct_families_with_kids, avg_hh_size, pct_no_vehicle, pct_renters, pct_bachelors_plus, pct_students(enrollment)` | Cache locally; never call live |
| Daytime population | **Census LODES WAC** | `workers_daytime, workers_high_wage` | |
| Restaurants (authoritative list) | **WPRDC Allegheny County Food Facilities** (geocoded, includes operational status, facility type) | Base `places` rows; `is_open` filter | Pittsburgh-specific win: solves the closed-restaurant problem |
| Restaurant quality / price / status | **Google Places** Nearby Search + Details with field masks (`rating, userRatingCount, priceLevel, businessStatus, types, editorialSummary`) | Per place: `rating, reviews, price_level, status` | Request county-wide once, spatial-index locally, aggregate to cells. Never per-hex calls |
| Anchors / activity generators | OSM (+ Foursquare): universities, schools, offices, hospitals, hotels, bars, clubs, malls, cinemas, stadiums, parks, attractions, transit stations | `anchor_counts{type}` within 500 m, `dist_to_nearest{type}` | |
| Foot traffic (relative) | **BestTime** hourly busyness forecasts for POIs in the county; fallback proxy = anchors + transit + workers + POI density | `activity_by_daypart{morning,lunch,afternoon,dinner,late_night,weekend}` per cell (distance-weighted POI aggregate) | Values are relative busyness, never visitor counts (§11.2) |
| Transit / access | GTFS (Pittsburgh Regional Transit): stops, daily trips; OSM roads, parking | `transit_daily_trips, main_road_frontage, parking_lots, walkable_poi_density` | |
| Spending capacity | BLS CEX food-away-from-home by income/age × ACS distribution; local price-tier distribution from Google `priceLevel` | `spending_capacity, local_price_profile{1..4}` | Call it capacity, not expenditure |
| Rent | Zillow ZORI (ZIP) + county assessor land value + 20–50 hand-collected asking rents → regression; sponsor pull if available | `est_rent_psf_yr, rent_confidence, rent_source, rent_resolution` | Always labeled estimate |
| Suppliers | OSM `shop=wholesale/supermarket/seafood/butcher/greengrocer` + hand list (Restaurant Depot, Strip District wholesalers, Sysco/US Foods depots, Asian/Italian import grocers) | `dist_to{supplier_type}_km` | |
| Properties (stretch) | `PropertyProvider` with three backends: real API (if a sponsor provides one), uploaded CSV, curated demo CSV of 10–20 real Pittsburgh vacancies | `properties` table | No scraping of LoopNet/Crexi (§11.2) |

Every feature row carries `source, geographic_resolution, updated_at` so the confidence score (§5.6) and the UI can be honest about a ZIP-level number sitting in a 170 m hex.

### 3.3 Tables

`geo_cells(h3, geom, lat, lng)` · `cell_features(h3, …all features above…, *_pct)` · `places(id, provider, provider_id, name, lat, lng, h3, categories[], cuisine_key, price_level, rating, reviews, is_chain, is_open, source, embedding vector(1024))` · `place_activity(place_id, daypart, busyness)` · `suppliers` · `properties(id, lat, lng, address, sqft, monthly_rent, rent_psf, ground_floor, has_hood, parking, source)` · `analyses(id, concept_json, weights_json, model_json, center, radius, created_at)` · `analysis_cells(analysis_id, h3, subscores_json, total, confidence, zone_id)`.

### 3.4 Cuisine affinity — observed, not ethnic

Do **not** model "many Korean residents → Korean restaurant will do well." It's statistically weak and reads as demographic steering. Affinity for cuisine *c* in a cell is built only from **revealed behavior**:

```
affinity[c] = pct( engagement of existing c-restaurants in grid_disk(2)      # Σ log1p(reviews)·rating
                 + 0.5 · engagement of cuisines complementary to c
                 + price compatibility between c's default tier and local_price_profile )
```

ACS ancestry/foreign-born tables are not ingested. Demographics still describe the market (age, income, families, students, vehicles) — they just never stand in for taste.

### 3.5 `cuisine_taxonomy.yaml`
~40 canonical cuisines with provider aliases, `complementary`, `substitutes`, `default_price_tier`, `default_dayparts`, `default_catchment` (walk/transit/drive), `supplier_types`. `concept_archetypes.yaml` combines cuisine × service format × price tier into ~100 archetypes for reverse mode.

---

## 4. Concept parser → Restaurant DNA

`POST /api/concept/parse {description}` → validated JSON (Pydantic; one retry on schema failure; cached by normalized text).

```python
class ConceptProfile(BaseModel):
    concept_name: str
    cuisines: list[str]; subcuisine: list[str]
    substitute_cuisines: list[str]; complementary_cuisines: list[str]
    service_format: Literal["quick_service","fast_casual","casual_dining","fine_dining","bar","cafe","ghost_kitchen"]
    price_tier: int; avg_ticket_usd: float
    dayparts: dict[str,float]                 # breakfast/lunch/dinner/late_night/weekend, sums to 1
    customer_archetypes: list[str]            # students, young_adults, office_workers, families, tourists, nightlife
    target_age_mix: dict[str,float]
    # 0–1 importances the weight generator uses
    dine_in_importance: float; takeout_importance: float; delivery_importance: float
    parking_importance: float; pedestrian_importance: float; transit_importance: float
    nightlife_importance: float; office_importance: float; university_importance: float
    family_importance: float; visibility_importance: float
    income_fit: Literal["low","low_to_medium","medium","medium_to_high","high"]
    catchment: Literal["walk","transit","drive"]; catchment_tau_min: float   # travel-time decay constant
    footprint_sqft: tuple[int,int]; seats: int
    supplier_types: list[str]
    direct_competitor_description: str        # natural-language, used for embedding
    is_franchise: bool
    proposed_weights: dict[str,float]         # backend validates & renormalizes (§5.5)
    confidence: float; clarifying_questions: list[str]
```

**UI:** show "Forkcast understood your concept as: *Affordable Korean fast-casual for students; relies on foot traffic, late-night, takeout and delivery*" plus editable chips. Corrections re-run the analysis. If `confidence < 0.5`, show `clarifying_questions` as chips first.

**Refine endpoint:** `POST /api/concept/refine {profile, instruction}` — "make it premium, $40 ticket, groups and parking" → patched profile → re-rank. This is the demo's money shot (§9).

---

## 5. Scoring engine (deterministic)

### 5.1 Candidates
Cells within radius (`ST_DWithin`), plus a `grid_disk(3)` halo for catchment and competition math. Drop cells with `pop_total + workers_daytime < 50` and no POIs.

### 5.2 Demand — gravity catchment
```
for cell i:  Demand_i = Σ_j  pop_j(daypart-weighted) × CustomerFit_j × SpendFit_j × exp(-t_ij / τ)
  pop_j(daypart) = Σ_d dayparts[d]·( residents_j·r_d + workers_j·w_d )     # r_lunch=.3,w_lunch=1; r_dinner=1,w_dinner=.2 …
  CustomerFit_j  = Σ archetype present-share (students→pct_students, office→workers_pct, families→pct_families_with_kids, nightlife→bar_density, tourists→hotels+attractions) weighted by the profile's importances
  SpendFit_j     = PriceMarketFit(price_tier, local_price_profile_j, income_fit)   # peaks at match, not at "richest"
  t_ij           = straight-line distance / speed(catchment)   # walk 5 km/h, transit 15, drive 30; v2: OSRM isochrones
```
`D = pct(log1p(Demand))`. Also emit `anchor_fit` = Σ importance × pct(anchor_counts) as a display sub-score (folded into D in v1).

### 5.3 Competition — semantic and distance-decayed
```
sim_k     = cosine( embed(profile.direct_competitor_description), places.embedding_k )   # Neapolitan 0.96, Italian 0.71, Domino's 0.58, Thai 0.08
           blended 0.6·embedding + 0.4·taxonomy(direct=1, substitute=0.5, complementary=0)
pop_k     = log1p(reviews_k) × rating_k / 5
Comp_i    = Σ_{k open, sim_k>0.35}  sim_k × pop_k × exp(-dist_ik / λ)     # λ from catchment: walk 400 m, transit 800 m, drive 2 km
Cluster_i = Σ_{k F&B or complementary anchors} exp(-dist_ik / 500 m)
Saturation_i = pct(Comp_i) - pct(Demand_i)
C = 100·(1 - sigmoid(3·Saturation_i)) + 15·pct(Cluster_i)·(1 - pct(Comp_i)),  clip 0–100
Gap_i = Demand_i / (1 + Comp_i)   →  "Cuisine White Space" metric, shown as Demand | Relevant supply | Market gap bars
gap_flag = pct(Demand_i) > .6 and Comp_i ≈ 0
```
Direct vs. indirect competitors are listed separately in the UI; complementary businesses count toward Cluster, not Comp.

### 5.4 Traffic fit, Access, Spending, Cost, Supply
```
T = pct( Σ_d dayparts[d] × activity_by_daypart_i[d] )          # concept decides which hours matter
A = pct( pedestrian_imp·walkable_poi_density + transit_imp·transit_trips + parking_imp·parking_lots + visibility_imp·main_road_frontage )
S_spend = pct( SpendFit_i × spending_capacity_i )
K = 100·clip( affordable_rent / est_annual_rent, 0, 1.5 )/1.5   # affordable = ticket×seats×turns(format)×300d×8%; if user gave a rent ceiling, hard-filter cells above it
Sup = 100·exp(-dist_to_needed_supplier_km / 8)                   # supplier type from profile
```

### 5.5 Weights — proposed by the LLM, validated by the backend
Defaults by service format; the parser's `proposed_weights` may override. Backend asserts `0 ≤ w ≤ 1`, clamps any single weight to ≤ 0.4, renormalizes, and **stores the final weights with the analysis**.

| format | D | C | T | A | S_spend | K | Sup |
|---|---|---|---|---|---|---|---|
| quick_service / fast_casual | .25 | .18 | .22 | .15 | .08 | .09 | .03 |
| casual_dining | .25 | .18 | .12 | .12 | .15 | .12 | .06 |
| fine_dining | .18 | .15 | .08 | .10 | .25 | .15 | .09 |
| cafe / bar | .25 | .15 | .25 | .17 | .08 | .07 | .03 |
| ghost_kitchen | .40 | .15 | .05 | .00 | .05 | .25 | .10 |

`total = Σ w·sub`. Sub-scores use metro-wide percentiles (so 80 means the same thing everywhere); the heatmap colors re-bucket within the radius for contrast.

### 5.6 Confidence
`confidence = mean( data_completeness, freshness, rent_confidence, traffic_source==real ? 1 : .5, min(1, n_places_in_disk/10) )`. Displayed next to every score: "Opportunity 91 · Confidence 63%".

### 5.7 Zones and de-duplication
Merge adjacent cells in the top decile into zones (H3 `grid_disk` connected components); rank zones by max cell; each zone gets a reverse-geocoded neighborhood name. The leaderboard shows zones, so the top-10 is not one neighborhood ten times.

### 5.8 Reverse mode
`POST /api/reverse {lat, lng, property?{sqft, monthly_rent}}` → for each of ~100 archetypes build a profile from `concept_archetypes.yaml`, score cells within 1 km (or the property's cell), rank by score with `+15 if gap_flag`. Return top 8 with sub-scores. ~100 passes × ~50 cells is sub-second in NumPy.

### 5.9 Validation (do not cut)
Backtest: for every open place with ≥30 reviews, build its profile from cuisine + price level, score its own cell, and compute Spearman ρ between total score and `log(reviews)`. Show ρ in the footer. Sanity-check the three demo concepts against local intuition (Oakland, Shadyside, South Side, Lawrenceville, Strip, Bloomfield). Note in the pitch that this is a survivorship-biased proxy (§11.2).

### 5.10 Model selection — decided by the coding agent

Nothing in this spec is a trained model yet; §5.2–5.5 is a hand-weighted scorer validated by the §5.9 backtest. **The coding agent must decide, and document in the README, which of the following it implements and why**, given the team size and the data actually available on day 0:

| Option | What it is | Labels needed | Effort |
|---|---|---|---|
| 0. Hand-weighted (baseline) | §5.5 as written; LLM proposes weights, backend validates | none | in plan |
| 1. Learned weights | Fit a regularized linear / gradient-boosted model of proxy success (log reviews, rating, reviews per year open) on cell features × concept features across open Pittsburgh restaurants; fitted coefficients replace the §5.5 defaults, LLM weights become a prior | proxy, from Google/WPRDC | a few hours |
| 2. Survival model | Reconstruct openings/closures from WPRDC facility-history snapshots; train logistic or survival model on (cell features at opening, cuisine, price tier, competition at the time) → P(survive 3 yr) | real, from WPRDC history | ~half a day; directly addresses survivorship bias |
| 3. Learning-to-rank | Pairwise ranker (e.g. LightGBM lambdarank) over (concept, cell) pairs using labels from 1 or 2 | as above | more than 24 h; post-hackathon |
| 4. Neighborhood look-alike | Embed neighborhoods; retrieve cells similar to those with successful examples of a concept but lacking one | none (unsupervised) | post-hackathon; expansion product |

Minimum requirement: option 0 must work end-to-end by the hour-10 checkpoint. Option 1 is the recommended add if hours 10–13 permit. Whatever is chosen, the README must state the model, its training data, its labels, and the backtest ρ. Pre-trained models are used as-is for the LLM and embeddings; do not fine-tune either.

The agent must also choose and record the specific models: the LLM for parsing/refining/explaining (any model with reliable JSON output), the embedding model for competitor similarity (§5.3), and any ML library for options 1–3. Record model names and versions in the README and in `analyses.model_json` so every result is reproducible.

### 5.11 Response
`RecommendResponse{ analysis_id, profile, weights, cells: GeoJSON FeatureCollection (properties: h3, total, D,C,T,A,S_spend,K,Sup, confidence, zone_id), zones: [ {zone_id, name, total, best_h3, subscores, drivers[3], risks[2], gap, competitors_direct[5], competitors_indirect[5], anchors[5], est_rent, properties[] } ], backtest_rho }`.

---

## 6. Explainer

`POST /api/explain {profile, zone}` → **Why here** (2 drivers with numbers) · **Top advantages** (3 bullets) · **Risks** (2–3 bullets, from the weakest sub-scores) · **Nearby** (named direct/indirect competitors and what they signal). Prompt receives only computed fields and is forbidden from inventing numbers. Compare endpoint takes up to 3 zones and returns one paragraph on the trade-off ("Oakland wins on student demand and gap; South Side wins if late-night revenue is the priority"). Report modal = top-3 zones + map thumbnail, print-to-PDF.

---

## 7. Frontend

- **Concept bar** with the three example chips; **Refine bar** appears after first run ("What if I make it premium?").
- **Map:** hex fill by opportunity (5 buckets, Excellent→Poor); numbered zone markers; **layer toggles**: Opportunity, Demand, Competition, Foot traffic, Spending, Rent, Suppliers, Transit, Properties. Toggling layers is how judges *see* why.
- **Leaderboard** of zones with 7 mini sub-score bars, confidence, gap badge, rent estimate; click → **Why-Here** panel (lazy `/explain`), competitor list, White-Space bars.
- **Compare** up to 3 zones → table + LLM trade-off paragraph.
- Reverse mode: pin a storefront → concept cards.
- Loading: "Parsing concept → Scoring 1,240 cells → Merging zones → Done". Target round trip < 3 s (parse cached, scoring NumPy, explain lazy).

---

## 8. Build order (24 h, two tracks)

| Hours | Track A — data & scoring | Track B — app |
|---|---|---|
| 0–1 | Repo, compose, keys (Census, Google, BestTime, embeddings); start Geofabrik PA download; agree `cell_features` schema and write `fixtures/` | Next.js + MapLibre skeleton centered on Pittsburgh; concept bar, pin, radius wired to fixture |
| 1–5 | Grid → ACS → LODES → WPRDC (open facilities) → OSM POIs/anchors/transit/supply → `cell_features` v1; sanity heatmap | Hex layer, layer toggles, leaderboard, profile chips |
| 5–8 | Google Places county-wide (field-masked, cached) → ratings/price/status; place embeddings → pgvector; BestTime for top ~500 POIs → daypart activity (proxy elsewhere) | Concept parser + refine endpoints, 3 golden tests, cache |
| 8–10 | Scoring engine (§5) + `/api/analysis`; zones; three demo concepts give plausible, *different* answers | Wire real API; loading states; Why-Here shell |
| **10** | **Integration checkpoint — end-to-end on the Korean street-food example. Freeze schemas.** | |
| 10–13 | Backtest, weight tuning or learned weights (§5.10 option 1), confidence score, store weights + model choices per analysis | Explainer, advantages/risks, White-Space bars, report modal |
| 13–16 | Rent regression (ZORI + hand-collected rents) → Cost; swap real traffic in if it arrived | Refine bar demo ("make it premium") polished; compare table |
| 16–19 | Reverse mode engine + archetypes; curated property CSV behind `PropertyProvider` | Reverse UI; property cards on top zones |
| 19–22 | Bug bash on the demo script; README | Deck (5 slides), rehearse |
| 22–24 | Buffer — nothing new | |

**Cut order if behind:** properties → reverse mode → compare → report → rent (show "n/a", K weight 0) → BestTime (proxy only). **Never cut:** editable profile chips, refine bar, backtest, layer toggles.

---

## 9. Demo (3 min)
1. "Cheap Korean street food under $15 for college students, open late." Pin Oakland, 3 mi. Heatmap lights Oakland/Shadyside/South Side corridors. Click #1: Student fit, late-night traffic, zero direct Korean competitors, White-Space bars.
2. Refine: "Turn this into premium Korean BBQ, $50/person, groups, parking." **The map moves** toward Shadyside/Downtown/suburban strips — Cost and Parking sub-scores visibly reweight. This is the proof it's concept-sensitive.
3. "Family steak & seafood, big dining room, parking, weekend dinners." Shifts again to suburban retail corridors.
4. Toggle Competition and Rent layers to show *why*. Flip to reverse mode on a real vacant storefront → top concepts.
5. Footer: "Backtested against N open Pittsburgh restaurants, ρ = 0.xx."

---

## 10. Open questions (ask before building)

Answered: US-only, Pittsburgh, ~24 h, sponsor budget, observed-affinity model (no ethnicity), no scraping.

1. Team size and each person's strongest area (data/geo vs. frontend)? With one builder, run Track A then B and drop properties + reverse up front.
2. Which paid APIs are *actually provisioned* on day 0 (Google Places? BestTime? Foursquare? any rent feed)? Build on proxies for anything not in hand.
3. Does the sponsor mandate a specific stack, cloud, or LLM/embedding provider that must appear in the demo?
4. Should the search center be Pittsburgh-only (precomputed) or any US address? Any-US is possible architecturally but only Pittsburgh will have features precomputed for the demo.
5. Reverse mode in the judged demo or "future work"? (It's cheap once forward mode exists but is the second thing cut.)
6. Is a curated CSV of 10–20 real vacant storefronts acceptable for the property feature?

---

## 11. Stretch features and concerns

### 11.1 Features (ranked by demo value ÷ effort)
1. **Refine-in-language** ("make it premium") — already in v1 plan; the single best differentiator.
2. **Layer toggles** — in v1; judges see the reasoning.
3. **Cuisine White Space / Void Detector** — city-wide scan: expected demand minus supply per cuisine per neighborhood → "Pittsburgh Food Opportunity Map." Landing-page visual and the municipality pitch.
4. **Concept Optimizer** — invert the problem: given a location, what changes to *my* concept raise the score ("$30 → $15–20, add late night, delivery, smaller footprint: 72 → 91"). Same engine, hill-climb over profile fields.
5. **Failure / what-if simulator** — drop a hypothetical competitor 400 m away, or raise rent $4k → $6k, and watch the rank change.
6. **Pareto shortlist** — instead of one number, show which zone wins on each axis (highest demand / highest spending / best rent efficiency) and the non-dominated set.
7. **Break-even scenario** — rent + seats + ticket + covers/day → months to break even, labeled "Scenario estimate" with assumptions shown.
8. **Two-stage property matching** — zone first, then property fit (sqft, rent, ground floor, hood/ventilation, frontage, parking, loading) with a Property Fit score.
9. **Property-owner marketplace** — landlords register vacancies, operators register concepts, both get matches ("a 1,400 sqft storefront matching your concept opened in your #2 zone").
10. **Review-gap analysis** — mine permitted review text for recurring unmet needs ("no late-night options," "too expensive," "no parking") → neighborhood unmet-needs profile → match against the concept.
11. **Neighborhood embeddings / Expansion mode** — embed neighborhoods; for chains, upload existing locations, learn the archetype, find look-alike neighborhoods minus cannibalization.
12. **Time-of-day animation** of the traffic layer.
13. **Delivery / ghost-kitchen mode** — isochrone-based demand, rent-heavy weights, traffic ignored.

### 11.2 Concerns
1. **Data arrival timing.** Vendor approvals can exceed 24 h. Apply at hour 0; build on proxies; hot-swap. Anything still a proxy at demo time is labeled "estimated."
2. **Closed restaurants distort competition.** Filter on WPRDC operational status and Google `businessStatus`; drop places with no reviews in 18 months.
3. **Foot traffic is relative.** BestTime values are % of a venue's own weekly peak. Never convert to visitor counts; use as a comparative signal only.
4. **False precision.** Show buckets plus the number, always with sub-scores and confidence. No "expected annual profit: $413,287." Any revenue figure is a labeled scenario with visible assumptions.
5. **Survivorship bias.** Existing restaurants are survivors; the backtest measures "what survivors look like," not what causes success. Say so in the pitch; long-term, ingest opening/closure history (WPRDC facility history helps here).
6. **Correlation ≠ causation.** A cluster of successful restaurants may also mean top-of-market rent or chain dominance. Show signals independently; never hide everything behind one model.
7. **Geographic granularity.** ZIP-level rent in a 170 m hex is not street-corner precision. Every feature stores `source, resolution, updated_at`; confidence reflects it.
8. **Fairness.** No ethnicity-as-taste modeling (§3.4). Demographics describe the market; they never steer by race. Keep the demo free of any "this neighborhood is X so serve Y" language.
9. **Licensing.** No scraping of Google Maps, Yelp, LoopNet, Crexi. Provider adapters make compliant swaps possible if this becomes a startup.
10. **API cost.** Field masks on Google Places; request county-wide once and spatially index locally; never per-hex calls; cache everything; precompute Pittsburgh so the live demo depends on nothing but the LLM and the database.
11. **Zoning and physical feasibility.** A perfect hex may not allow a restaurant (zoning, liquor license, hood/grease trap, ADA, occupancy). Out of scope for v1; the property-fit stage (11.1 #8) is where it lands.
12. **LLM parse errors** silently ruin rankings — editable chips are the safety net; log every parse and every weight set.
13. **Scope.** The MVP story is: describe → Forkcast understands → map lights up → refine → map moves → click → understand why. Everything else is stretch.
14. **Not financial or real-estate advice** — one-line disclaimer.
