# Forkcast — Lessons

Struggles, surprises, and trial-and-error worth not repeating.

## Environment

**The machine had neither Python 3.11 nor Docker.** The pinned wheels
(`pyarrow`, `geopandas`, `pydantic`) do not build on Python 3.14, which was the
only interpreter present. Fixed by installing `uv`, then
`uv python install 3.11`, and changing the Makefile `venv` target to
`uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt`.
Teammates should run `make venv` and get the same interpreter.

**Colima replaced Docker Desktop.** It is headless, needs no GUI step and no
license prompt. `brew install colima docker docker-compose`, then
`colima start --cpu 2 --memory 4`. The `docker compose` plugin needs
`~/.docker/config.json` to contain
`{"cliPluginsExtraDirs":["/opt/homebrew/lib/docker/cli-plugins"]}`.
The `docker-compose.yml` in the repo is identical either way, so a teammate on
Docker Desktop is unaffected.

**The `postgis/postgis:16-3.4` image fails `apt-get update`** with
"Release file ... is expired". The fix is
`apt-get -o Acquire::Check-Valid-Until=false update` in `docker/db/Dockerfile`.
Bumping to `16-3.5` is not an option: that tag has no arm64 image.

## Data

**The county has 18,275 H3 res-9 cells, not the ~7,000 the proposal estimated.**
Allegheny County is about 1,930 km² and a res-9 cell is about 0.105 km², so
roughly 18,300 is the correct figure. This matters for the scoring engine's
in-memory arrays and for anything that assumed a 7k row count.

**The Census API rejects keyless requests.** It answers a request with no
`CENSUS_API_KEY` with a 302 to `missing_key.html` and the header
`X-DataWebAPI-KeyError: 1`. The metadata endpoint
(`.../variables.html`) does work without a key, which is enough to verify
variable codes but not to pull data. A free key is required before Task 5 can
produce `data/processed/acs.parquet`.

## Process

**Plan defects surface in two places, and both are worth the time.** The
pre-flight scan of the plan caught two before any code was written: a test that
projected polygons at longitude 0–2 into the Pennsylvania state-plane CRS
(changed to `EPSG:6933`, a world equal-area projection), and a merge that would
raise `TypeError` when Google returned no match and `types` was `NaN` rather
than a list. The per-task reviews then caught a broken `ruff` invocation and a
`FutureWarning` that would have polluted every pipeline run.

**A subagent's session can die mid-task.** One implementer lost its OAuth
session after writing the code but before committing. The work was recovered
from the working tree by a second implementer. The lesson is to keep the ledger
at `.superpowers/sdd/<plan>/progress.md` current, because it is what survives.

## Providers

**The LLM provider moved from Anthropic to Gemini, and the embedding provider
moved with it.** `gemini-3.8-flash` now does parse, refine, explain and compare;
`gemini-embedding-001` replaces Voyage `voyage-3` for competitor similarity.
Because no `api/` LLM code had been written yet, the change was confined to
documentation, `.env`, `requirements.txt` and the Task 11 brief. Consolidating on
one provider also removed a key the team no longer has to provision.

**Gemini returns normalized embedding vectors only at its native 3072
dimensions.** We request `output_dimensionality=1024` so the vector fits the
existing `places.embedding vector(1024)` column without a migration, which means
the ingest script must L2-normalize the vectors itself. Google's documentation is
explicit: "If you are using `gemini-embedding-001`, you must manually normalize
non-3072 dimensions." Cosine similarity is scale-invariant so rankings would
survive the omission, but pgvector's inner-product operator and every downstream
reader assume unit length.

**`google-genai` forced a pydantic upgrade.** It requires `pydantic>=2.12.5`,
and the repo pinned `pydantic==2.9.2`, so a fresh `make venv` would have failed
to resolve. The pin moved to `2.13.5`. All 22 tests and `ruff` still pass, so
`api/models.py` and the contract mirrors were unaffected.

## Scoring

**`spending_capacity` is close to a restatement of population density.** Measured
across all 18,275 cells, it correlates with raw `hh_count` at Pearson 0.965. The
formula is `hh_count * sum(income_share * bracket_value)`, and the CEX bracket
values span only about 5.2x while household counts span orders of magnitude, so
the household term dominates. The income mix does influence the result — two
cells with equal households but different income mix differ by up to 5.2x — but
it is clearly the secondary term.

This matters because the Demand sub-score is a separate gravity catchment over
population. Spending-fit and Demand may therefore be near-duplicates, and the
headline Opportunity Score may carry density at roughly double the intended
weight. A task-level review confirmed the ingest implementation is faithful to
its contract, so this is a modeling property rather than a bug. **Phase 2 should
measure both sub-scores' contributions in the backtest before tuning weights by
hand**, and the weight validator is the place to resolve it.

**There is currently no high-end price signal anywhere in the data.** Google
`price_level` reaches only 101 places, all of them levels 1 and 2, because the
Places quota limited enrichment to about 4% of the county. Until the county-wide
pull completes, the demo's "make it premium" refine has nothing to compare
against, and `local_price_3` and `local_price_4` are zero for every cell.

## Fixtures — read this before building against `recommend_sample.json` (Dev 3)

**`zones[i].drivers`, `.risks`, `.gap` and `.competitors_indirect` are
byte-identical across all 5 zones in `data/fixtures/recommend_sample.json`** —
same `["Student demand 91st pct", ...]`, same `{"demand":82,"supply":20,"gap":62}`,
same `"Sushi Fuku"` competitor at `distance_m: 210` on every zone, even though the
5 zones sit at 5 different real locations with 5 different subscore profiles.
This is fixture placeholder text, not a rendering bug — if a zone panel shows the
same competitor/driver copy no matter which zone you click, that is expected
until Phase 2's `/api/explain` endpoint exists and produces the real per-zone
narrative. `zone.total`, `zone.subscores` and `zone.best_h3` are the genuinely
derived fields (they match that zone's entry in `cells.features` exactly) and
can be trusted for anything that reads scores rather than narrative text. See
the comment in `ingest/make_fixtures.py` at the `zones.append(...)` call for
where this is generated.

## Phase 2 planning findings (not yet acted on)

**The backtest sample is N=131, not the whole county.** Only 167 of 15,295 places
carry a rating and review count, because Google enrichment reached ~4%. A Spearman
correlation on 131 points will have a confidence interval wide enough to cross zero.
Report the CI and the N alongside rho, and say "not distinguishable from chance" when
it does — a bare rho on this sample would overstate what was measured.

**`local_price_*` is absent on 97.4% of cells, not merely zero for tiers 3 and 4.**
Only 477 of 18,275 cells have any priced place nearby. The earlier reading — that
tiers 3 and 4 are a true measured zero — is right but incomplete: for most cells the
whole price profile is absent, which is a different thing from a measured absence of
expensive restaurants. A "make it premium" refine is therefore driven by income fit
rather than by an observed high-end market.

**Percentile base is a real open question.** Ranking Demand and Competition within the
search area rather than county-wide is far cheaper — a county-wide per-request
competition pass is roughly 25M place-cell pairs — but it breaks the proposal's
promise in §5.5 that "80 means the same thing everywhere". Whichever is chosen, the
interface must say which, because the two numbers are not comparable.
