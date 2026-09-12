"""Gemini gemini-embedding-001 embeddings for every place → pgvector."""
import json
import os
import time

import numpy as np
import pandas as pd
from google import genai
from google.genai import errors, types
from sqlalchemy import text

from ingest import common

MODEL = "gemini-embedding-001"
DIMS = 1024
BATCH = 100
MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_RETRY_DELAY = 30.0


def embed_text(row: pd.Series) -> str:
    raw_cats = row.get("categories")
    cats_list = [] if raw_cats is None else list(raw_cats)
    cats = ", ".join(c.replace("_", " ") for c in cats_list)
    parts = [row["name"], cats, row.get("summary") or ""]
    return ". ".join(p for p in parts if p).rstrip(".") + "."


def l2_normalize(v: list[float]) -> list[float]:
    a = np.asarray(v, dtype=float)
    return (a / np.linalg.norm(a)).tolist()


def _find_key(node, key):
    """First value of `key` found anywhere in a nested dict/list error payload, or None."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


def _is_per_minute_quota(e: errors.APIError) -> bool:
    """True for a retryable per-minute (or other short-window) rate limit; False for a daily/
    terminal quota exhaustion. Distinguished by the quotaId Google embeds in the QuotaFailure
    error detail: a short-window cap's id contains "PerMinute", a daily cap's does not. Checking
    for that substring rather than one hardcoded quotaId string keeps this correct as the exact
    id (model, tier) varies."""
    quota_id = _find_key(getattr(e, "details", None), "quotaId")
    return bool(quota_id) and "PerMinute" in quota_id


def _retry_delay_seconds(e: errors.APIError) -> float | None:
    """Seconds to wait from the error's RetryInfo detail (e.g. "40s"), or None if absent/unparseable."""
    raw = _find_key(getattr(e, "details", None), "retryDelay")
    if not raw:
        return None
    try:
        return float(str(raw).rstrip("s"))
    except ValueError:
        return None


def fetch_embeddings(todo: pd.DataFrame, client, config, cache_file, batch: int = BATCH,
                      sleep=time.sleep) -> dict:
    """id -> normalized embedding for every row in todo. Catches per batch, not around the whole
    fetch. A per-minute rate limit (retryable) sleeps for the server's retryDelay, or a default
    backoff, and retries the same batch, up to MAX_RATE_LIMIT_RETRIES consecutive times so a
    genuinely stuck run cannot spin forever. A daily/terminal quota exhaustion (or a rate limit
    that exceeds the retry cap) stops the fetch but keeps every embedding already paid for,
    appended to cache_file as it goes, rather than discarding it. main() then writes the parquet
    and DB rows for whatever came back — zero batches fetched degrades to no rows, a partial run
    writes just the ids that succeeded."""
    done = {}
    with cache_file.open("a") as f:
        i = 0
        retries = 0
        while i < len(todo):
            chunk = todo.iloc[i:i + batch]
            try:
                res = client.models.embed_content(
                    model=MODEL,
                    contents=[embed_text(r) for _, r in chunk.iterrows()],
                    config=config,
                )
            except errors.APIError as e:
                if _is_per_minute_quota(e) and retries < MAX_RATE_LIMIT_RETRIES:
                    retries += 1
                    wait = _retry_delay_seconds(e) or DEFAULT_RETRY_DELAY
                    print(f"embeddings: rate limited on batch {i // batch + 1} ({e}); "
                          f"retry {retries}/{MAX_RATE_LIMIT_RETRIES} after {wait:.0f}s")
                    sleep(wait)
                    continue
                print(f"embeddings: fetch stopped at batch {i // batch + 1} ({e}); "
                      f"keeping {len(done)} embeddings from batches that succeeded")
                break
            for pid, emb in zip(chunk.id, res.embeddings):
                v = l2_normalize(emb.values)
                done[pid] = v
                f.write(json.dumps({"id": pid, "v": v}) + "\n")
            i += batch
            retries = 0
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
    if len(todo) and os.environ.get("GEMINI_API_KEY"):
        client = genai.Client()
        config = types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=DIMS)
        done.update(fetch_embeddings(todo, client, config, cache))
    elif len(todo):
        print(f"embeddings: GEMINI_API_KEY not set, skipping {len(todo)} unembedded place(s); emitting cache only")
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
