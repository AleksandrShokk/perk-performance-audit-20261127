import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from redis import Redis

from app.core.config import get_settings
from app.integrations.wildberries.data import Source
from app.modules.sync.quota import addresses, gate_key, preserve_legacy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PERK_INTEGRATION_TESTS") != "1", reason="Requires isolated Redis"
    ),
]


@pytest.fixture
def quota(vault):
    redis = Redis.from_url(get_settings().redis_broker_url, decode_responses=True)
    basic = SimpleNamespace(seller_id=str(uuid4()), token_type=1)
    personal = SimpleNamespace(seller_id=basic.seller_id, token_type=3)
    try:
        yield redis, vault, basic, personal
    finally:
        keys = {
            key
            for source in Source
            for meta in (basic, personal)
            for key in addresses(vault, source, meta)
        }
        redis.delete(*keys)
        redis.close()


def test_unknown_legacy_limit_is_inherited_conservatively(quota):
    redis, vault, _, personal = quota
    current, legacy, _ = addresses(vault, Source.FINANCE, personal)
    redis.set(legacy, "1", ex=43200)
    assert gate_key(redis, vault, Source.FINANCE, personal) == current
    assert redis.ttl(current) >= 43198


def test_confirmed_type_change_preserves_basic_without_delaying_personal(quota):
    redis, vault, basic, personal = quota
    old, legacy, origin = addresses(vault, Source.FINANCE, basic)
    redis.set(legacy, "1", ex=43200)
    preserve_legacy(redis, vault, basic)
    current = gate_key(redis, vault, Source.FINANCE, personal)
    assert redis.get(origin) == "1" and redis.ttl(old) >= 43198
    assert redis.ttl(legacy) >= 43198 and redis.ttl(current) == -2


def test_same_type_tokens_share_seller_quota_and_never_shorten_wait(quota):
    redis, vault, _, personal = quota
    key, legacy, _ = addresses(vault, Source.SALES, personal)
    redis.set(key, "1", ex=7200)
    redis.set(legacy, "1", ex=600)
    another = SimpleNamespace(seller_id=personal.seller_id, token_type=3)
    assert gate_key(redis, vault, Source.SALES, another) == key
    assert redis.ttl(key) >= 7198


def test_personal_existing_wait_survives_basic_transition(quota):
    redis, vault, basic, personal = quota
    current, legacy, _ = addresses(vault, Source.FINANCE, personal)
    redis.set(current, "1", ex=120)
    redis.set(legacy, "1", ex=43200)
    preserve_legacy(redis, vault, basic)
    gate_key(redis, vault, Source.FINANCE, personal)
    assert 118 <= redis.ttl(current) <= 120
