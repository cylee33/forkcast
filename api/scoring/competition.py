"""Competition sub-score C (§5.3): semantic + distance-decayed competitor pressure,
blended with a cuisine-cluster bonus, expressed as saturation relative to Demand.

Embedding coverage is 900 of 15,295 places (Task 11, Gemini daily quota). A place with no
embedding falls back to the taxonomy term ALONE -- never to similarity=0, which would
silently understate a same-cuisine competitor just because ingest hasn't reached it yet.

Scoring must make no network call (every API key is quota-limited), so
`profile.direct_competitor_description` cannot be embedded at request time. Instead we
build a proxy query vector as the mean embedding of already-embedded places sharing one of
`profile.cuisines` (a same-cuisine centroid standing in for "embed this concept's own
description"). If no embedded place shares a cuisine with the profile, the embedding term
is skipped for every place (the blend collapses to taxonomy alone) -- disclosed, not faked.

D20: measured cosine similarity only spans ~0.69-0.90, so it is min-max rescaled across the
embedded candidate set before blending 0.6*embedding + 0.4*taxonomy -- otherwise, at weight
0.6, it would carry only ~+/-0.09 of usable variation against taxonomy's full 0/0.5/1 range.
"""
import numpy as np
import pandas as pd

from api.scoring import geo

SIM_THRESHOLD = 0.35
DIRECT_SIM = 0.6
EMBED_WEIGHT, TAXONOMY_WEIGHT = 0.6, 0.4
CLUSTER_ANCHOR_COLS = ["anchor_bar", "anchor_nightclub"]


def taxonomy_sim(profile, cuisine_keys: pd.Series) -> pd.Series:
    direct = set(profile.cuisines)
    substitute = set(profile.substitute_cuisines)

    def score(c):
        if c in direct:
            return 1.0
        if c in substitute:
            return 0.5
        return 0.0  # complementary or unrelated: 0 in the taxonomy term (§5.3)

    return cuisine_keys.fillna("").map(score)


def _query_vector(profile, places: pd.DataFrame, embeddings: pd.DataFrame) -> np.ndarray | None:
    same_cuisine = places["cuisine_key"].isin(profile.cuisines)
    ids = places.loc[same_cuisine, "id"]
    ids = ids[ids.isin(embeddings.index)]
    if ids.empty:
        return None
    vecs = np.stack(embeddings.loc[ids, "embedding"].to_numpy())
    return vecs.mean(axis=0)


def blended_similarity(profile, places: pd.DataFrame, embeddings: pd.DataFrame) -> pd.Series:
    """places: open places (any subset of columns is fine as long as id/cuisine_key are
    present). Returns a Series aligned to `places.index`."""
    tax = taxonomy_sim(profile, places["cuisine_key"])
    has_embed = places["id"].isin(embeddings.index)
    query = _query_vector(profile, places, embeddings) if has_embed.any() else None
    if query is None:
        return tax

    idx = places.index[has_embed]
    emb_ids = places.loc[idx, "id"]
    vecs = np.stack(embeddings.loc[emb_ids, "embedding"].to_numpy())
    qn = query / (np.linalg.norm(query) or 1.0)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    cos = (vecs / norms) @ qn
    lo, hi = cos.min(), cos.max()
    rescaled = (cos - lo) / (hi - lo) if hi > lo else np.full_like(cos, 0.5)

    blended = tax.copy()
    blended.loc[idx] = EMBED_WEIGHT * rescaled + TAXONOMY_WEIGHT * tax.loc[idx].to_numpy()
    return blended


def comp_and_cluster(profile, open_places: pd.DataFrame, embeddings: pd.DataFrame,
                      features: pd.DataFrame, targets: list[str]) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (Comp_i, Cluster_i, sim) for each h3 in `targets`. `sim` is aligned to
    `open_places.index` (reused by the caller for competitor listings)."""
    sim = blended_similarity(profile, open_places, embeddings)
    keep = sim > SIM_THRESHOLD
    pop_k = np.log1p(open_places["reviews"].fillna(0.0)) * (open_places["rating"].fillna(0.0) / 5.0)
    lam = geo.COMP_LAMBDA_KM[profile.catchment]

    tlat = features.loc[targets, "lat"].to_numpy()[:, None]
    tlng = features.loc[targets, "lng"].to_numpy()[:, None]
    if keep.any():
        plat = open_places.loc[keep, "lat"].to_numpy()[None, :]
        plng = open_places.loc[keep, "lng"].to_numpy()[None, :]
        dist_km = geo.haversine_km(tlat, tlng, plat, plng)
        decay = np.exp(-dist_km / lam)
        weight = (sim[keep] * pop_k[keep]).to_numpy()
        comp = decay @ weight
    else:
        comp = np.zeros(len(targets))
    comp = pd.Series(comp, index=targets)

    # Cluster_i (§5.3: sum of exp(-dist/500m) over nearby F&B / complementary anchors) --
    # cell_features already carries restaurants_open and anchor_bar/anchor_nightclub as
    # grid_disk(~500m)-smoothed counts, which is the same radius, so we reuse those
    # precomputed columns rather than re-running a second distance-decay matrix.
    tf = features.loc[targets]
    cluster = tf["restaurants_open"].fillna(0.0).copy()
    for col in CLUSTER_ANCHOR_COLS:
        cluster = cluster + tf[col].fillna(0.0)

    return comp, cluster, sim
