CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS geo_cells (
  h3 TEXT PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  geom GEOMETRY(Polygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS geo_cells_geom_idx ON geo_cells USING GIST (geom);

CREATE TABLE IF NOT EXISTS cell_features (
  h3 TEXT PRIMARY KEY REFERENCES geo_cells(h3),
  features JSONB NOT NULL,          -- all numeric columns, incl. *_pct
  cuisine_affinity JSONB NOT NULL,  -- {cuisine_key: 0-100}
  activity_by_daypart JSONB NOT NULL,
  traffic_source TEXT NOT NULL,     -- real | proxy
  rent_source TEXT, rent_resolution TEXT, rent_confidence DOUBLE PRECISION,
  source JSONB NOT NULL,            -- {column: source}
  resolution JSONB NOT NULL,        -- {column: resolution}
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS places (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL, provider_id TEXT,
  name TEXT NOT NULL, lat DOUBLE PRECISION NOT NULL, lng DOUBLE PRECISION NOT NULL,
  h3 TEXT NOT NULL,
  categories TEXT[] NOT NULL DEFAULT '{}',
  cuisine_key TEXT, price_level INTEGER, rating DOUBLE PRECISION, reviews INTEGER,
  is_chain BOOLEAN NOT NULL DEFAULT false, is_open BOOLEAN NOT NULL DEFAULT true,
  source TEXT NOT NULL, summary TEXT,
  embedding VECTOR(1024)
);
CREATE INDEX IF NOT EXISTS places_h3_idx ON places (h3);

CREATE TABLE IF NOT EXISTS place_activity (
  place_id TEXT REFERENCES places(id), daypart TEXT NOT NULL, busyness DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (place_id, daypart)
);

CREATE TABLE IF NOT EXISTS suppliers (
  id TEXT PRIMARY KEY, name TEXT, supplier_type TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL, lng DOUBLE PRECISION NOT NULL, h3 TEXT NOT NULL, source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY, concept_json JSONB NOT NULL, weights_json JSONB NOT NULL, model_json JSONB NOT NULL,
  center_lat DOUBLE PRECISION, center_lng DOUBLE PRECISION, radius_mi DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analysis_cells (
  analysis_id TEXT REFERENCES analyses(id), h3 TEXT NOT NULL,
  subscores_json JSONB NOT NULL, total DOUBLE PRECISION NOT NULL, confidence DOUBLE PRECISION NOT NULL, zone_id INTEGER,
  PRIMARY KEY (analysis_id, h3)
);
CREATE TABLE IF NOT EXISTS concept_cache (
  normalized_text TEXT PRIMARY KEY, profile_json JSONB NOT NULL, model TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS zone_names (h3 TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backtest_results (
  id SERIAL PRIMARY KEY, rho DOUBLE PRECISION NOT NULL, n INTEGER NOT NULL, model TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
