# UI prototype with local ML signal

Run the prototype and API from the repository root:

```sh
.venv/bin/uvicorn api.main:app --reload
```

Then open `http://127.0.0.1:8000/`. The FastAPI process serves the prototype,
the Oakland response fixture, and the optional historical-popularity route from the
same origin.

When the ignored files under `ml/artifacts/` are present, Analyze sends the candidate
H3 IDs and a small cuisine/price profile to `POST /api/popularity`. Street cards,
cell tooltips, and the detail panel show the returned Pittsburgh-wide percentile as a
separate historical signal. It never changes the opportunity score or its ranking.

Without the private artifacts, the rest of the prototype continues to work and labels
the historical signal unavailable. The browser's keyword-to-cuisine mapping is only a
demo adapter until the concept parser endpoint lands. Pittsburgh has no Yelp outcome
labels in the downloaded dataset, so the UI must keep the inference-only label visible.
