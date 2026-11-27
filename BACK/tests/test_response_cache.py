from datetime import date
from types import SimpleNamespace

from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy.dialects import postgresql

from app.core import response_cache
from app.modules.insights import product_labels


class Page(BaseModel):
    total: int
    items: list[str]


class FakeRedis:
    def __init__(self):
        self.values, self.ttl = {}, {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key], self.ttl[key] = value, ex

    def expire(self, key, seconds):
        self.ttl[key] = seconds


class BrokenRedis:
    def get(self, key):
        raise RedisError

    def set(self, key, value, ex=None):
        raise RedisError


def request(vault, redis):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(vault=vault, redis=redis)))


def test_second_read_returns_the_stored_body_without_recalculation(vault):
    redis, calls = FakeRedis(), []

    def build():
        calls.append(1)
        return Page(total=2, items=["a", "b"])

    first = response_cache.respond(request(vault, redis), "page", ["rev-1"], {"limit": 2}, build)
    second = response_cache.respond(request(vault, redis), "page", ["rev-1"], {"limit": 2}, build)
    assert first.body == second.body == b'{"total":2,"items":["a","b"]}'
    assert second.media_type == "application/json"
    assert len(calls) == 1
    # Bodies are sealed and keys are keyed digests: nothing readable is stored.
    [(key, value)] = redis.values.items()
    assert "rev-1" not in key and "items" not in value
    assert redis.ttl[key] == response_cache.CACHE_SECONDS


def test_new_data_or_other_parameters_never_reuse_an_answer(vault):
    redis, calls = FakeRedis(), []

    def build():
        calls.append(1)
        return Page(total=len(calls), items=[])

    state = request(vault, redis)
    response_cache.respond(state, "page", ["rev-1"], {"limit": 2}, build)
    response_cache.respond(state, "page", ["rev-2"], {"limit": 2}, build)
    response_cache.respond(state, "page", ["rev-2"], {"limit": 3}, build)
    response_cache.respond(state, "other", ["rev-2"], {"limit": 3}, build)
    assert len(calls) == 4


def test_without_fingerprint_or_redis_the_response_is_calculated(vault):
    page = Page(total=1, items=["x"])
    assert response_cache.respond(request(vault, FakeRedis()), "p", None, {}, lambda: page) is page
    response = response_cache.respond(request(vault, BrokenRedis()), "p", ["r"], {}, lambda: page)
    assert response.body == page.model_dump_json().encode()


def test_searches_are_kept_briefly(vault):
    redis = FakeRedis()
    response_cache.respond(
        request(vault, redis),
        "page",
        ["rev"],
        {"q": "abc"},
        lambda: Page(total=0, items=[]),
        response_cache.SEARCH_CACHE_SECONDS,
    )
    assert list(redis.ttl.values()) == [response_cache.SEARCH_CACHE_SECONDS]


def test_only_wildberries_read_models_are_fingerprinted():
    ozon = SimpleNamespace(id="s", name="Ozon", marketplace="ozon")
    assert response_cache.wb_fingerprint(None, "w", [ozon], []) is None
    assert response_cache.wb_fingerprint(None, "w", [], []) is None


def test_funnel_label_lookup_is_a_bounded_key_range():
    statements = []

    class Db:
        def begin_nested(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            statements.append(statement)
            return []

    product_labels.funnel_labels(Db(), "w", "s", {"42"}, date(2025, 11, 27), date(2026, 11, 26))
    sql = str(
        statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    # A year view searches only its last 31 days, through the primary-key range.
    assert "wb_records.record_key >= '2026-10-27:'" in sql
    assert "wb_records.record_key < '2026-11-27:'" in sql
