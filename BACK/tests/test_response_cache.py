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


class PipelineRedis(FakeRedis):
    def mget(self, keys):
        return [self.values.get(key) for key in keys]

    def pipeline(self, transaction=True):
        redis = self

        class Pipe:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def set(self, key, value, ex=None):
                redis.set(key, value, ex=ex)

            def execute(self):
                return []

        return Pipe()


def test_funnel_labels_are_searched_once_and_misses_expire_sooner(vault):
    redis = PipelineRedis()
    cache = product_labels.LabelCache(
        redis, vault, "w", "s", date(2026, 11, 20), date(2026, 11, 26)
    )
    assert cache.known({"1", "2"}) == {}
    cache.store({"1", "2"}, {"1": "VEND-1"})
    assert cache.known({"1", "2", "3"}) == {"1": "VEND-1", "2": None}
    assert sorted(redis.ttl.values()) == [
        product_labels.LabelCache.MISSING_SECONDS,
        product_labels.LabelCache.FOUND_SECONDS,
    ]
    # A miss is remembered only for the same period; a found code for any period.
    other = product_labels.LabelCache(
        redis, vault, "w", "s", date(2026, 11, 13), date(2026, 11, 19)
    )
    assert other.known({"1", "2"}) == {"1": "VEND-1"}
    # Another store never sees these entries.
    assert product_labels.LabelCache(redis, vault, "w", "x", None, None).known({"1"}) == {}
    assert all("VEND" not in value for value in redis.values.values())


def test_part_of_a_response_is_cached_as_its_model(vault):
    redis, calls = FakeRedis(), []

    def build():
        calls.append(1)
        return Page(total=3, items=["a"])

    first = response_cache.cached_model(redis, vault, "part", ["r"], {}, Page, build)
    second = response_cache.cached_model(redis, vault, "part", ["r"], {}, Page, build)
    assert first == second == Page(total=3, items=["a"]) and first is not second
    assert len(calls) == 1
    assert response_cache.cached_model(None, vault, "part", ["r"], {}, Page, build) == first
    assert len(calls) == 2


def test_home_funnel_periods_match_the_web_app(monkeypatch):
    from app.modules.insights import compute

    # Friday 28.11.2026: yesterday is Thursday 27.11.
    monkeypatch.setattr(compute, "moscow_today", lambda: date(2026, 11, 28))
    periods = compute.home_funnel_periods()
    expected = [
        (date(2026, 11, 21), date(2026, 11, 27)),  # 7 days, as in the HAR
        (date(2026, 11, 14), date(2026, 11, 20)),  # its comparison period
        (date(2026, 11, 14), date(2026, 11, 27)),  # 14 days
        (date(2026, 10, 31), date(2026, 11, 13)),
        (date(2026, 10, 31), date(2026, 11, 27)),  # 28 days, as in the HAR
        (date(2026, 10, 3), date(2026, 10, 30)),
        (date(2026, 11, 23), date(2026, 11, 27)),  # week: Monday..yesterday
        (date(2026, 11, 18), date(2026, 11, 22)),
    ]
    assert [p for p in expected if p != compute.default_period()] == periods
    warmed = [params for kind, params in compute.warm_defaults() if kind == "funnel"]
    assert {"date_from": "2026-10-31", "date_to": "2026-11-27", "currency": None} in warmed
