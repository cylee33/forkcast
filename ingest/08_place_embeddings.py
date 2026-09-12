"""Gemini gemini-embedding-001 embeddings for every place → pgvector."""
import json

import numpy as np
import pandas as pd
from google import genai
from google.genai import errors, types
from sqlalchemy import text

from ingest import common

MODEL = "gemini-embedding-001"
DIMS = 1024
BATCH = 100


def embed_text(row: pd.Series) -> str:
    raw_cats = row.get("categories")
    cats_list = [] if raw_cats is None else list(raw_cats)
    cats = ", ".join(c.replace("_", " ") for c in cats_list)
    parts = [row["name"], cats, row.get("summary") or ""]
    return ". ".join(p for p in parts if p).rstrip(".") + "."


def l2_normalize(v: list[float]) -> list[float]:
    a = np.asarray(v, dtype=float)
    return (a / np.linalg.norm(a)).tolist()


def fetch_embeddings(todo: pd.DataFrame, client, config, cache_file, batch: int = BATCH) -> dict:
    """id -> normalized embedding for every row in todo. Catches per batch, not around the whole
    fetch: a quota outage partway through stops the fetch but keeps every embedding already paid
    for, appended to cache_file as it goes, rather than discarding it. main() then writes the
    parquet and DB rows for whatever came back — zero batches fetched degrades to no rows, a
    partial run writes just the ids that succeeded."""
    done = {}
    with cache_file.open("a") as f:
        for i in range(0, len(todo), batch):
            chunk = todo.iloc[i:i + batch]
            try:
                res = client.models.embed_content(
                    model=MODEL,
                    contents=[embed_text(r) for _, r in chunk.iterrows()],
                    config=config,
                )
            except errors.APIError as e:
                print(f"embeddings: fetch stopped at batch {i // batch + 1} ({e}); "
                      f"keeping {len(done)} embeddings from batches that succeeded")
                break
            for pid, emb in zip(chunk.id, res.embeddings):
                v = l2_normalize(emb.values)
                done[pid] = v
                f.write(json.dumps({"id": pid, "v": v}) + "\n")
    return done


def main():
    args = common.cli(__doc__)
    places = common.load("places")
    if args.limit:
        places = places.head(args.limit)
    cache = common.RAW / "gemini/embeddings.jsonl"
    cache.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if cache.exists():
        for line in cache.read_text().splitlines():
            r = json.loads(line)
            done[r["id"]] = r["v"]
    todo = places[~places.id.isin(done)]
    client = genai.Client()
    config = types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=DIMS)
    done.update(fetch_embeddings(todo, client, config, cache))
    have = places[places.id.isin(done)]
    out = pd.DataFrame({"id": have.id, "embedding": [done[i] for i in have.id]})
    common.save(out, "place_embeddings")
    if not args.no_db:
        with common.engine().begin() as con:
            for pid, v in zip(out.id, out.embedding):
                con.execute(text("UPDATE places SET embedding = :v WHERE id = :id"), {"v": json.dumps(list(v)), "id": pid})
    print(f"embeddings: {len(out)}/{len(places)} places, model {MODEL}, dims {DIMS}")


if __name__ == "__main__":
    main()
