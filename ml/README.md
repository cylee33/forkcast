# Optional popularity model

This module exposes a Yelp-trained historical popularity signal without changing the seven deterministic opportunity subscores or the frozen response contracts.

```python
from ml.popularity import score_profile

result = score_profile(profile, candidate_h3_ids)
```

The result contains `h3`, `predicted_log_popularity`, metro-fixed `popularity_pct`, `demographic_missing_count`, and `outside_training_range_count`. The same H3 receives the same percentile when the analysis radius changes. Unsupported cuisine keys are reported through `result.attrs`; if none of the requested cuisines are supported, the model uses its explicit `unknown` category.

`predicted_log_popularity` estimates an association with `log1p(review_count)` in the downloaded Yelp snapshot. `popularity_pct` is a Pittsburgh-wide relative rank. Neither field is revenue, survival, causal location lift, a success probability, or a validated Pittsburgh outcome. Keep it outside `D`, `C`, `T`, `A`, `S_spend`, `K`, `Sup`, and `total` unless a later contract change and validation explicitly decide otherwise.

The analysis endpoint can add the signal to its GeoJSON cells without changing the
seven subscores or their total:

```python
from ml.popularity import enrich_cell_collection

response.cells = enrich_cell_collection(response.cells, response.profile)
```

When the local artifacts exist, this adds `historical_popularity_log`,
`historical_popularity_pct`, `historical_popularity_demographic_missing_count`, and
`historical_popularity_outside_training_range_count` to every cell's `properties`.
When they are absent, it returns an unchanged copy by default. Pass `required=True`
if a private deployment should fail instead. The current response schema allows extra
cell properties, so this does not alter the frozen required fields.

## Local artifacts

The repository intentionally ignores `ml/artifacts/`. The Yelp Dataset Terms restrict sharing Data and related metrics with third parties and require Yelp review before a public presentation or publication involving the Data or Yelp brand. Do not commit, push, publish, or place the trained model, evaluation metrics, or derived demographic lookup in a submission package without resolving those terms.

On the authorized local development machine, build the runtime files from the completed isolated experiment:

```sh
PYTHONPATH=. .venv/bin/python ml/build_popularity_assets.py \
  --experiment /absolute/path/to/forkcast/experiments/yelp
```

The default runtime directory is `ml/artifacts`. A private deployment can point to another local or mounted directory with `FORKCAST_POPULARITY_ARTIFACTS=/path/to/artifacts`. Required files are:

- `yelp_popularity_hgb.joblib`
- `pittsburgh_h3_demographics.parquet`
- `yelp_popularity_metadata.json`

The model was selected using Indianapolis validation data and evaluated once on Nashville. Pittsburgh has no Yelp labels in this dataset version; the Pittsburgh artifact only broadcasts the same ACS 2021 tract definitions used in training to H3 cell centers.

When the local files are present, run `pytest tests/test_popularity.py`. On a clean public checkout these integration tests skip with the reason that the restricted local artifacts are absent; the rest of the test suite remains runnable.
