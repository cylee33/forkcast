# cell_features columns

Stored as `cell_features.features` JSONB and as `data/processed/cell_features.parquet` (one column each).
Every numeric column `X` also has `X_pct` (metro-wide percentile, 0–100), **except** the `dist_to_*_km`
columns, whose `_pct` is inverted (100 − raw percentile): a higher `dist_to_*_pct` means *closer*, not
farther — e.g. `dist_to_university_km` near its max (~15 km) percentiles near 0, and near its min
(~0.04 km) percentiles near 100. Do not re-invert it when treating distance as a cost.

`source` and `resolution` are static, column-level methodology labels (e.g. `est_rent_psf_yr` always
asserts `zori_manual_regression`), not per-row provenance — they describe the intended pipeline, not what
actually produced a given row. For rent and traffic, the per-row columns are authoritative instead:
`rent_source`, `rent_resolution`, `rent_confidence`, and `traffic_source` (all row-level; `rent_source`
and `rent_resolution` may be NULL where no rent part was joined, but `rent_confidence` is always
present, reading 0.0 when there is no estimate).

`median_hh_income` and `avg_hh_size` may be NULL where the Census could not produce an estimate for
that block group — this means *no estimate*, not a value of zero, so do not treat it as $0 income or
0 persons. Their `_pct` companions (`median_hh_income_pct`, `avg_hh_size_pct`) are NULL alongside.

`cell_features.parquet` has no `updated_at` column; that column exists only on the DB `cell_features` table.

Sources/resolutions live in the `source` / `resolution` JSONB maps keyed by column name.

| Column | Unit | Source | Resolution |
|---|---|---|---|
| pop_total, hh_count | count | ACS 5yr 2023 | block group, area-weighted |
| median_hh_income | USD | ACS | block group |
| income_lt25k, income_25_50k, income_50_75k, income_75_100k, income_100_150k, income_150k_plus | share 0–1 | ACS B19001 | block group |
| pct_age_18_24, pct_age_25_34, pct_age_35_54, pct_age_55p | share | ACS B01001 | block group |
| pct_families_with_kids | share | ACS B11005 | block group |
| avg_hh_size | persons | ACS B25010 | block group |
| pct_no_vehicle | share | ACS B25044 | block group |
| pct_renters | share | ACS B25003 | block group |
| pct_bachelors_plus | share | ACS B15003 | block group |
| pct_students | share | ACS B14007 (college/grad enrolled) | block group |
| workers_daytime, workers_high_wage | count | LODES WAC 2021 | block group (block rolled up), area-weighted |
| restaurants_open | count | WPRDC + Google | point, grid_disk(1) smoothed |
| anchor_university, anchor_school, anchor_office, anchor_hospital, anchor_hotel, anchor_bar, anchor_nightclub, anchor_mall, anchor_cinema, anchor_stadium, anchor_park, anchor_attraction, anchor_transit_station | count within ~500 m (grid_disk(2)) | OSM | point |
| dist_to_university_km, dist_to_hospital_km, dist_to_transit_station_km, dist_to_stadium_km | km | OSM | point |
| transit_daily_trips | count | GTFS (PRT) stop_times in cell + grid_disk(1) | point |
| main_road_frontage | 0/1 | OSM highway=primary/secondary/tertiary intersects cell | line |
| parking_lots | count | OSM amenity=parking, grid_disk(1) | point |
| walkable_poi_density | count | OSM shops+amenities, grid_disk(2) | point |
| poi_density | count | all OSM POIs in cell | point |
| activity_morning, activity_lunch, activity_afternoon, activity_dinner, activity_late_night, activity_weekend | relative 0–100 | BestTime (real) or proxy | point, distance-weighted |
| traffic_source | real / proxy | — | — |
| spending_capacity | USD/yr food-away-from-home per HH × HH | CEX × ACS | block group |
| local_price_1, local_price_2, local_price_3, local_price_4 | share | Google priceLevel, grid_disk(2) | point |
| est_rent_psf_yr, rent_confidence, rent_source, rent_resolution | USD/sqft/yr, 0–1, text, text | ZORI ZIP + manual rents regression | ZIP |
| dist_to_wholesale_km, dist_to_supermarket_km, dist_to_seafood_km, dist_to_butcher_km, dist_to_greengrocer_km, dist_to_asian_grocer_km, dist_to_italian_grocer_km | km | OSM + hand list | point |
| cuisine_affinity | {cuisine_key: 0–100} | derived (§3.4) | grid_disk(2) |
