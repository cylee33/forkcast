"""Gemini gemini-embedding-001 embeddings for every place → pgvector."""
import json

import numpy as np
import pandas as pd
from google import genai
from google.genai import types
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
    with cache.open("a") as f:
        for i in range(0, len(todo), BATCH):
            chunk = todo.iloc[i:i + BATCH]
            res = client.models.embed_content(
                model=MODEL,
                contents=[embed_text(r) for _, r in chunk.iterrows()],
                config=config,
            )
            for pid, emb in zip(chunk.id, res.embeddings):
                v = l2_normalize(emb.values)
                done[pid] = v
                f.write(json.dumps({"id": pid, "v": v}) + "\n")
    out = pd.DataFrame({"id": places.id, "embedding": [done[i] for i in places.id]})
    common.save(out, "place_embeddings")
    if not args.no_db:
        with common.engine().begin() as con:
            for pid, v in zip(out.id, out.embedding):
                con.execute(text("UPDATE places SET embedding = :v WHERE id = :id"), {"v": json.dumps(list(v)), "id": pid})
    print(f"embeddings: {len(out)} places, model {MODEL}, dims {DIMS}")


if __name__ == "__main__":
    main()
