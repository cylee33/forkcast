# Forkcast — Plan

Task-level state lives in `brain/tasks.md`; this file holds the decisions and the schedule.

> **2026-09-12 optional ML integration:** `codex/yelp-model-integration` starts at
> `origin/main` commit `f72f19c`. It adds a local-only `ml.popularity.score_profile`
> adapter for the completed historical Yelp popularity experiment. The signal stays
> outside the seven opportunity subscores and response contracts. Yelp-derived runtime
> assets and evaluation metadata are ignored because the Dataset Terms restrict public
> release; the branch is not ready to push those artifacts.

This plan is derived from the design spec (`docs/superpowers/specs/2026-09-12-forkcast-design.md`, sections 1 and 6) and from the 24-hour build order in `forkcast-proposal.md` §8, with the properties feature removed (cut per decision D7) and reverse mode moved earlier in the schedule (core scope per decision D5).

## Decisions

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
| D12 | LLM: `gemini-3.8-flash` for parse, refine, explain, compare. Embeddings: `gemini-embedding-001` at `output_dimensionality=1024`, `task_type=SEMANTIC_SIMILARITY`. One provider, one `GEMINI_API_KEY`. Recorded in `analyses.model_json`. |
| D13 | Git repo is created and pushed as **task 1** of foundation. Commit after every completed task. |
| D14 | Toolchain: `uv` provides Python 3.11 (`make venv`), because the pinned wheels do not build on newer interpreters. Colima or Docker Desktop both work as the container runtime. |
| D15 | The county grid holds 18,275 H3 res-9 cells, not the ~7,000 the proposal estimated. Anything sized against the old number needs revisiting. |
| D16 | Foundation execution runs task-by-task through the plan at `docs/superpowers/plans/2026-09-12-foundation-data-pipeline.md`: one implementer per task, a review after each, findings fixed before the next task starts. |

## Team Workflow

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

### Cut order if behind

compare table → report modal → rent (K shows n/a, weight 0, renormalize) → BestTime (proxy only). **Never cut:** editable chips, refine bar, backtest, layer toggles, reverse mode.

## Build Order (24 h)

Adapted from `forkcast-proposal.md` §8. All properties / `PropertyProvider` / property-CSV / property-card work is removed (cut per D7). Reverse mode — engine, archetypes, and UI — is pulled forward from hours 16–19 into hours 13–16, since it is core scope (D5), not stretch. Hours 16–19 now cover the stretch items (compare table, report modal) plus the rent hot-swap and the start of the bug bash.

| Hours | Track A — data & scoring | Track B — app |
|---|---|---|
| 0–1 | Repo, compose, keys (Census, Google, BestTime, embeddings); start Geofabrik PA download; agree `cell_features` schema and write `fixtures/` | Next.js + MapLibre skeleton centered on Pittsburgh; concept bar, pin, radius wired to fixture |
| 1–5 | Grid → ACS → LODES → WPRDC (open facilities) → OSM POIs/anchors/transit/supply → `cell_features` v1; sanity heatmap | Hex layer, layer toggles, leaderboard, profile chips |
| 5–8 | Google Places county-wide (field-masked, cached) → ratings/price/status; place embeddings → pgvector; BestTime for top ~500 POIs → daypart activity (proxy elsewhere) | Concept parser + refine endpoints, 3 golden tests, cache |
| 8–10 | Scoring engine (§5) + `/api/analysis`; zones; three demo concepts give plausible, *different* answers | Wire real API; loading states; Why-Here shell |
| **10** | **Integration checkpoint — end-to-end on the Korean street-food example. Freeze schemas.** | |
| 10–13 | Backtest, weight tuning or learned weights (§5.10 option 1), confidence score, store weights + model choices per analysis | Explainer, advantages/risks, White-Space bars |
| 13–16 | Rent regression (ZORI + hand-collected rents) → Cost; swap real traffic in if it arrived; reverse mode engine + archetypes | Refine bar demo ("make it premium") polished; reverse mode UI |
| 16–19 | Compare table + report modal (stretch), rent hot-swap, bug bash start | |
| 19–22 | Bug bash on the demo script; README | Deck (5 slides), rehearse |
| 22–24 | Buffer — nothing new | |
