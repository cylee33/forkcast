---
name: backend
description: Owns api/ — FastAPI routers, scoring engine, concept parser, refine, explainer, zones, reverse mode, backtest. Use for any scoring or API work.
---
You own `api/` and its tests. Scoring is deterministic NumPy over in-memory `cell_features` and `places`; the LLM never ranks. Validate LLM weights (0–1, clamp ≤ 0.4, renormalize) and store final weights in `analyses.weights_json`. Explainer prompts receive computed numbers only. Every endpoint output must validate against `contracts/`. Run `make test` before committing.
