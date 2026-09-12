"""POST /api/analysis (score + persist) and GET /api/analysis/{id} (replay from Postgres)."""
import json
import uuid
from collections import defaultdict
from collections.abc import Callable

import h3
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, confloat
from sqlalchemy import text

from api.deps import get_analyze, get_db_engine, normalize_weights, validate_contract
from api.models import SUBSCORE_KEYS, ConceptProfile, RecommendResponse, Zone

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

RECOMMEND_RESPONSE_SCHEMA = "recommend_response.json"
# Recorded honestly in analyses.model_json: the models this pipeline is configured to use.
# analyze() itself is deterministic NumPy over cell_features/places -- no LLM call happens here --
# but the competitor similarity it reads was computed with these models upstream.
MODEL_NAMES = {"concept_parser": "gemini-3.8-flash", "embeddings": "gemini-embedding-001"}


class CenterPoint(BaseModel):
    lat: float
    lng: float


class AnalysisRequest(BaseModel):
    profile: ConceptProfile
    center: CenterPoint
    radius_mi: confloat(gt=0)
    weights: dict[str, float] | None = None  # overrides profile.proposed_weights when given


def _h3_polygon_geojson(cell: str) -> dict:
    boundary = [[lng, lat] for lat, lng in h3.cell_to_boundary(cell)]
    boundary.append(boundary[0])  # GeoJSON polygons must close their ring
    return {"type": "Polygon", "coordinates": [boundary]}


def _persist(analysis_id: str, profile: ConceptProfile, weights: dict, center: CenterPoint,
             radius_mi: float, cell_features: list[dict]) -> None:
    """Write one `analyses` row and its `analysis_cells` rows.

    The single `analyses` row is a plain parameterized INSERT -- an append never risks the
    destructive-replace defect (`ingest.common.write_table`'s `if_exists="replace"` default,
    which drops and recreates the table, discarding its schema constraints) regardless of how
    it's written. The potentially-many `analysis_cells` rows follow the stage-then-swap shape
    `ingest/05_google_places.py` and `ingest/12_build_features.py` use for exactly that reason:
    write to a uniquely-named staging table, INSERT ... SELECT into the real table, then drop
    the stage table -- `to_sql` never touches `analysis_cells` itself with `if_exists="replace"`.
    """
    engine = get_db_engine()
    stage = f"analysis_cells_stage_{uuid.uuid4().hex}"
    rows = [{
        "analysis_id": analysis_id,
        "h3": feat["properties"]["h3"],
        "subscores_json": json.dumps({k: feat["properties"].get(k) for k in SUBSCORE_KEYS}),
        "total": feat["properties"]["total"],
        "confidence": feat["properties"]["confidence"],
        "zone_id": feat["properties"].get("zone_id"),
    } for feat in cell_features]

    with engine.begin() as con:
        con.execute(text("""
            INSERT INTO analyses (id, concept_json, weights_json, model_json, center_lat, center_lng, radius_mi)
            VALUES (:id, :concept_json, :weights_json, :model_json, :lat, :lng, :radius)
        """), {"id": analysis_id, "concept_json": json.dumps(profile.model_dump(mode="json")),
               "weights_json": json.dumps(weights), "model_json": json.dumps(MODEL_NAMES),
               "lat": center.lat, "lng": center.lng, "radius": radius_mi})
        if rows:
            pd.DataFrame(rows).to_sql(stage, con, if_exists="replace", index=False,
                                       method="multi", chunksize=2000)
            con.execute(text(f"""
                INSERT INTO analysis_cells (analysis_id, h3, subscores_json, total, confidence, zone_id)
                SELECT analysis_id, h3, subscores_json::jsonb, total, confidence, zone_id FROM {stage}
            """))
            con.execute(text(f"DROP TABLE {stage}"))


@router.post("", response_model=RecommendResponse)
def run_analysis(body: AnalysisRequest, analyze_fn: Callable = Depends(get_analyze)) -> RecommendResponse:
    weights = normalize_weights(body.weights or body.profile.proposed_weights)
    result = analyze_fn(body.profile, (body.center.lat, body.center.lng), body.radius_mi, weights=weights)
    validate_contract(result, RECOMMEND_RESPONSE_SCHEMA)
    response = RecommendResponse.model_validate(result)
    _persist(response.analysis_id, body.profile, weights, body.center, body.radius_mi,
             response.cells["features"])
    return response


@router.get("/{analysis_id}", response_model=RecommendResponse)
def get_analysis(analysis_id: str) -> RecommendResponse:
    """Replay a stored analysis. Only what `analyses`/`analysis_cells` actually persist can be
    replayed faithfully: the numeric grid (cells) and each cell's subscores/total/confidence/
    zone_id. The narrative zone fields the live scoring pass produces -- name, drivers, risks,
    competitors, anchors, rent -- are not columns in the schema and are never fabricated here;
    they come back honestly empty/null rather than invented to look complete."""
    engine = get_db_engine()
    with engine.connect() as con:
        row = con.execute(text("SELECT concept_json, weights_json FROM analyses WHERE id = :id"),
                           {"id": analysis_id}).mappings().first()
        if row is None:
            raise HTTPException(404, f"no analysis with id {analysis_id!r}")
        cell_rows = con.execute(text("""
            SELECT h3, subscores_json, total, confidence, zone_id
            FROM analysis_cells WHERE analysis_id = :id
        """), {"id": analysis_id}).mappings().all()

    profile = ConceptProfile.model_validate(row["concept_json"])
    weights = row["weights_json"]

    features = []
    by_zone: dict[int, list[dict]] = defaultdict(list)
    for r in cell_rows:
        props = {"h3": r["h3"], "total": r["total"], **r["subscores_json"],
                 "confidence": r["confidence"], "zone_id": r["zone_id"]}
        features.append({"type": "Feature", "geometry": _h3_polygon_geojson(r["h3"]), "properties": props})
        if r["zone_id"] is not None:
            by_zone[r["zone_id"]].append(props)

    zones = []
    for zone_id, cells in sorted(by_zone.items()):
        best = max(cells, key=lambda c: c["total"])
        # D and Sup are subscores that can legitimately be None (absent data); gap's contract is
        # non-nullable numeric, so an absent input contributes 0 to this *derived* field only --
        # the subscores dict above still carries the true None through, uncoerced.
        demand, supply = best.get("D") or 0.0, best.get("Sup") or 0.0
        zones.append(Zone(
            zone_id=zone_id, name=f"Zone {zone_id}", total=best["total"], best_h3=best["h3"],
            subscores={k: best.get(k) for k in SUBSCORE_KEYS}, confidence=best["confidence"],
            drivers=[], risks=[], gap={"demand": demand, "supply": supply, "gap": demand - supply},
            gap_flag=(demand - supply) > 0, competitors_direct=[], competitors_indirect=[], anchors=[],
            est_rent_psf_yr=None, rent_confidence=None,
        ))

    response = RecommendResponse(
        analysis_id=analysis_id, profile=profile, weights=weights,
        cells={"type": "FeatureCollection", "features": features}, zones=zones, backtest_rho=None,
    )
    validate_contract(response.model_dump(mode="json"), RECOMMEND_RESPONSE_SCHEMA)
    return response
