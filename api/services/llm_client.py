"""Shared Gemini access for api/services/*: disk cache, rate-limit retry, graceful
degradation. A cache hit never makes a network call. Mirrors the retry shape of
ingest/08_place_embeddings.py (per-minute quota retries with the server's retryDelay;
a daily/terminal quota, or a missing key, degrades to None rather than raising)."""
import hashlib
import json
import os
import pathlib
import re
import time

from google.genai import errors, types
from pydantic import BaseModel, ValidationError

MODEL = "gemini-3.8-flash"
ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data/raw/llm"
MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_RETRY_DELAY = 20.0


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


def _is_per_minute_quota(e: "errors.APIError") -> bool:
    quota_id = _find_key(getattr(e, "details", None), "quotaId")
    return bool(quota_id) and "PerMinute" in quota_id


def _retry_delay_seconds(e: "errors.APIError") -> float | None:
    raw = _find_key(getattr(e, "details", None), "retryDelay")
    if not raw:
        return None
    try:
        return float(str(raw).rstrip("s"))
    except ValueError:
        return None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _cache_path(purpose: str, cache_input: str) -> pathlib.Path:
    key = hashlib.sha256(f"{purpose}:{normalize(cache_input)}".encode()).hexdigest()
    d = CACHE_DIR / purpose
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def read_cache(purpose: str, cache_input: str):
    p = _cache_path(purpose, cache_input)
    if p.exists():
        return json.loads(p.read_text())
    return None


def write_cache(purpose: str, cache_input: str, data) -> None:
    _cache_path(purpose, cache_input).write_text(json.dumps(data))


def client_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _call_with_retry(client, prompt: str, config, sleep):
    """One live generate_content call, retrying a per-minute rate limit with the
    server's retryDelay. Returns the response, or None on a terminal/exhausted quota."""
    retries = 0
    while True:
        try:
            return client.models.generate_content(model=MODEL, contents=prompt, config=config)
        except errors.APIError as e:
            if _is_per_minute_quota(e) and retries < MAX_RATE_LIMIT_RETRIES:
                retries += 1
                sleep(_retry_delay_seconds(e) or DEFAULT_RETRY_DELAY)
                continue
            return None


def generate_structured(purpose: str, cache_input: str, prompt: str, schema: type[BaseModel],
                         sleep=time.sleep) -> BaseModel | None:
    """Returns a validated `schema` instance from the disk cache (keyed on normalized
    `cache_input`, never touching the network) or, on a miss, a live call with structured
    output and one retry on a Pydantic validation failure. Returns None -- never raises --
    when the key is absent, the quota is exhausted, or both attempts fail to validate."""
    cached = read_cache(purpose, cache_input)
    if cached is not None:
        try:
            return schema.model_validate(cached)
        except ValidationError:
            pass  # corrupt/stale cache entry: fall through to a live call
    if not client_available():
        return None
    from google import genai
    client = genai.Client()
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema)
    for _ in range(2):  # one retry on a validation failure
        resp = _call_with_retry(client, prompt, config, sleep)
        if resp is None:
            return None
        try:
            parsed = schema.model_validate_json(resp.text)
        except ValidationError:
            continue
        write_cache(purpose, cache_input, json.loads(resp.text))
        return parsed
    return None


def generate_text(purpose: str, cache_input: str, prompt: str, sleep=time.sleep) -> str | None:
    """Plain-text counterpart to generate_structured: cached, rate-limit-retried, and
    None (never an exception) when the key is absent or the quota is exhausted."""
    cached = read_cache(purpose, cache_input)
    if cached is not None:
        return cached.get("text")
    if not client_available():
        return None
    from google import genai
    client = genai.Client()
    resp = _call_with_retry(client, prompt, None, sleep)
    if resp is None:
        return None
    write_cache(purpose, cache_input, {"text": resp.text})
    return resp.text
