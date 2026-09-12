import numpy as np
import pandas as pd
from google.genai import errors

from tests.conftest import load_script


def test_embed_text_composes_name_categories_summary():
    e = load_script("08_place_embeddings")
    row = pd.Series({"name": "Seoul Bulgogi", "categories": ["korean_restaurant", "restaurant"], "summary": "Casual Korean."})
    assert e.embed_text(row) == "Seoul Bulgogi. korean restaurant, restaurant. Casual Korean."


def test_embed_text_handles_categories_as_numpy_array():
    """places.parquet actually stores categories as a numpy object array, not a list. `arr or []`
    raises ValueError('ambiguous truth value') for any array with more than one element — the real
    bug this test guards against, which the list-based test above cannot catch."""
    e = load_script("08_place_embeddings")
    row = pd.Series({"name": "Seoul Bulgogi",
                     "categories": np.array(["korean_restaurant", "restaurant"], dtype=object),
                     "summary": "Casual Korean."})
    assert e.embed_text(row) == "Seoul Bulgogi. korean restaurant, restaurant. Casual Korean."


def test_l2_normalize_gives_unit_length():
    e = load_script("08_place_embeddings")
    out = e.l2_normalize([3.0, 4.0])
    assert np.isclose(np.linalg.norm(out), 1.0)
    assert np.allclose(out, [0.6, 0.8])


class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeResponse:
    def __init__(self, n):
        self.embeddings = [_FakeEmbedding([1.0, 0.0]) for _ in range(n)]


def test_fetch_embeddings_keeps_batches_fetched_before_a_later_batch_fails(tmp_path):
    """A quota failure partway through the fetch must not discard the batches that already
    succeeded — the exact bug that hit the real run (900/15295 embedded, then a 429) and that
    main() must be able to persist rather than lose."""
    e = load_script("08_place_embeddings")
    todo = pd.DataFrame({"id": ["a", "b", "c"], "name": ["A", "B", "C"],
                        "categories": [np.array(["x"]), np.array(["y"]), np.array(["z"])],
                        "summary": ["", "", ""]})
    calls = []

    def fake_embed_content(model, contents, config):
        calls.append(contents)
        if len(calls) == 2:
            raise errors.APIError(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}})
        return _FakeResponse(len(contents))

    class FakeModels:
        embed_content = staticmethod(fake_embed_content)

    class FakeClient:
        models = FakeModels()

    cache_file = tmp_path / "embeddings.jsonl"
    done = e.fetch_embeddings(todo, FakeClient(), config=None, cache_file=cache_file, batch=1)

    assert list(done.keys()) == ["a"]  # batch "b" raised; "c" never attempted
    assert len(calls) == 2
    assert cache_file.read_text().strip().splitlines() == [
        '{"id": "a", "v": [1.0, 0.0]}'
    ]


def test_main_survives_absent_gemini_key_without_calling_client(monkeypatch, tmp_path):
    """With no GEMINI_API_KEY, main() must not construct genai.Client() at all -- constructing it
    unconditionally is what raised ValueError('No API key was provided') and aborted the whole
    `make ingest` chain before steps 09-12 ever ran. Exercise this with the key unset; no live call
    should ever happen here."""
    e = load_script("08_place_embeddings")
    monkeypatch.setattr(e.common, "RAW", tmp_path / "raw")
    monkeypatch.setattr(e.common, "PROC", tmp_path / "processed")
    (tmp_path / "processed").mkdir(parents=True)
    places = pd.DataFrame({"id": ["p1", "p2"], "name": ["A", "B"],
                            "categories": [np.array(["x"]), np.array(["y"])], "summary": ["", ""]})
    places.to_parquet(tmp_path / "processed" / "places.parquet", index=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["08_place_embeddings.py", "--no-db"])

    def _boom(*a, **k):
        raise AssertionError("genai.Client() must not be constructed when no key is set")
    monkeypatch.setattr(e.genai, "Client", _boom)

    e.main()  # must not raise
    out = pd.read_parquet(tmp_path / "processed" / "place_embeddings.parquet")
    assert len(out) == 0  # nothing embedded, but the parquet is still emitted from cache


def test_fetch_embeddings_returns_all_ids_when_nothing_fails(tmp_path):
    e = load_script("08_place_embeddings")
    todo = pd.DataFrame({"id": ["a", "b"], "name": ["A", "B"],
                        "categories": [np.array(["x"]), np.array(["y"])], "summary": ["", ""]})

    def fake_embed_content(model, contents, config):
        return _FakeResponse(len(contents))

    class FakeModels:
        embed_content = staticmethod(fake_embed_content)

    class FakeClient:
        models = FakeModels()

    cache_file = tmp_path / "embeddings.jsonl"
    done = e.fetch_embeddings(todo, FakeClient(), config=None, cache_file=cache_file, batch=100)
    assert set(done.keys()) == {"a", "b"}


def _quota_error(quota_id, retry_delay=None):
    """Build an APIError shaped like Google's real 429 body: a QuotaFailure detail carrying
    quotaId, and (for a per-minute limit) a RetryInfo detail carrying retryDelay."""
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": quota_id, "quotaValue": "100"}]}]
    if retry_delay is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay})
    return errors.APIError(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED",
                                            "details": details}})


def test_fetch_embeddings_retries_a_per_minute_rate_limit_and_continues(tmp_path):
    """A per-minute rate limit (quotaId ends in PerMinute..., carries a retryDelay) is transient:
    the real fix must sleep for the server's retryDelay and retry the same batch rather than
    giving up, so a run that hits it makes progress instead of stopping at 0."""
    e = load_script("08_place_embeddings")
    todo = pd.DataFrame({"id": ["a", "b"], "name": ["A", "B"],
                        "categories": [np.array(["x"]), np.array(["y"])], "summary": ["", ""]})
    calls = []
    sleeps = []

    def fake_embed_content(model, contents, config):
        calls.append(contents)
        if len(calls) == 1:
            raise _quota_error("EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier",
                                retry_delay="40s")
        return _FakeResponse(len(contents))

    class FakeModels:
        embed_content = staticmethod(fake_embed_content)

    class FakeClient:
        models = FakeModels()

    cache_file = tmp_path / "embeddings.jsonl"
    done = e.fetch_embeddings(todo, FakeClient(), config=None, cache_file=cache_file, batch=100,
                               sleep=sleeps.append)

    assert set(done.keys()) == {"a", "b"}  # the batch that hit the rate limit was retried
    assert len(calls) == 2  # one failed attempt, one retry that succeeded
    assert sleeps == [40.0]  # slept for the server's retryDelay, not a made-up default


def test_fetch_embeddings_stops_on_a_daily_quota_and_keeps_what_it_has(tmp_path):
    """A daily/terminal quota (quotaId has no PerMinute window, no retryDelay to retry against)
    must still stop immediately and keep whatever batches already succeeded -- the deliberate
    behavior from the earlier fix, which this change must not disturb."""
    e = load_script("08_place_embeddings")
    todo = pd.DataFrame({"id": ["a", "b", "c"], "name": ["A", "B", "C"],
                        "categories": [np.array(["x"]), np.array(["y"]), np.array(["z"])],
                        "summary": ["", "", ""]})
    calls = []

    def fake_embed_content(model, contents, config):
        calls.append(contents)
        if len(calls) == 2:
            raise _quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        return _FakeResponse(len(contents))

    class FakeModels:
        embed_content = staticmethod(fake_embed_content)

    class FakeClient:
        models = FakeModels()

    def _no_sleep(_):
        raise AssertionError("a daily quota must not sleep/retry")

    cache_file = tmp_path / "embeddings.jsonl"
    done = e.fetch_embeddings(todo, FakeClient(), config=None, cache_file=cache_file, batch=1,
                               sleep=_no_sleep)

    assert list(done.keys()) == ["a"]  # batch "b" hit the daily cap and stopped the fetch
    assert len(calls) == 2  # "c" was never attempted


def test_fetch_embeddings_caps_consecutive_rate_limit_retries(tmp_path):
    """A rate limit that never clears (server keeps returning 429 for the same batch) must not
    spin forever -- after MAX_RATE_LIMIT_RETRIES consecutive retries it falls through to the
    terminal path and keeps what was already fetched."""
    e = load_script("08_place_embeddings")
    todo = pd.DataFrame({"id": ["a", "b"], "name": ["A", "B"],
                        "categories": [np.array(["x"]), np.array(["y"])], "summary": ["", ""]})
    calls = []
    sleeps = []

    def fake_embed_content(model, contents, config):
        calls.append(contents)
        if len(calls) == 1:
            return _FakeResponse(len(contents))
        raise _quota_error("EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier",
                            retry_delay="1s")

    class FakeModels:
        embed_content = staticmethod(fake_embed_content)

    class FakeClient:
        models = FakeModels()

    cache_file = tmp_path / "embeddings.jsonl"
    done = e.fetch_embeddings(todo, FakeClient(), config=None, cache_file=cache_file, batch=1,
                               sleep=sleeps.append)

    assert list(done.keys()) == ["a"]  # "b" retried repeatedly but never got through
    assert len(calls) == 1 + 1 + e.MAX_RATE_LIMIT_RETRIES  # "a" once, "b" attempted + all retries
    assert len(sleeps) == e.MAX_RATE_LIMIT_RETRIES
