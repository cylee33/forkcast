# places table

| Column | Notes |
|---|---|
| id | `wprdc:<facility_id>` or `google:<place_id>` when no WPRDC match |
| provider, provider_id | origin row |
| name, lat, lng, h3 | h3 at res 9 |
| categories | text[] from Google `types` + WPRDC description |
| cuisine_key | canonical key from `ingest/cuisine_taxonomy.yaml`, nullable |
| price_level | 1–4 from Google `priceLevel`, nullable |
| rating, reviews | Google `rating`, `userRatingCount`, nullable |
| is_chain | name matches taxonomy `chains` list |
| is_open | WPRDC status open AND Google businessStatus != CLOSED_PERMANENTLY |
| source | `wprdc+google`, `wprdc`, `google` |
| summary | Google editorialSummary text |
| embedding | vector(1024), voyage-3 on `name. categories. summary` |
