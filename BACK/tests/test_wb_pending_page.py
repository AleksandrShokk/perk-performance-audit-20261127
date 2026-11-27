from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.integrations.wildberries.data import Page
from app.modules.sync import pending_page


@pytest.fixture
def pending(vault):
    run = SimpleNamespace(
        workspace_id=uuid4(),
        store_id=uuid4(),
        id=uuid4(),
        source="funnel",
        cursor={"day": "2026-10-01", "offset": 0},
    )
    redis = Mock()
    storage = {}
    redis.get.side_effect = storage.get
    redis.set.side_effect = lambda key, value, **kwargs: storage.update({key: value}) or True
    key = pending_page.address(vault, run, "encrypted-credential")
    return run, redis, storage, key


def test_roundtrip_keeps_decimal_strings_and_encrypted_normalized_fields(pending, vault):
    _, redis, storage, key = pending
    records = {"2026-10-01:42": {"revenue": "951968.12", "count": 119}}
    page = Page([], {"day": "2026-09-30", "offset": 0}, False, cooldown_seconds=60)
    assert pending_page.save(redis, vault, key, records, page)
    redis.set.assert_called_once_with(key, storage[key], ex=600)
    assert "951968" not in storage[key] and "revenue" not in storage[key]
    result = pending_page.load(redis, vault, key)
    assert result.records == records and result.cursor == page.cursor and result.complete is False


@pytest.mark.parametrize(
    "field", ["workspace_id", "store_id", "id", "source", "cursor", "credential"]
)
def test_page_is_bound_to_tenant_run_cursor_and_credential(pending, vault, field):
    run, redis, storage, key = pending
    pending_page.save(redis, vault, key, {}, Page([], {}, True))
    credential = "encrypted-credential"
    if field == "credential":
        credential = "replacement-credential"
    else:
        setattr(run, field, {} if field == "cursor" else str(uuid4()))
    other = pending_page.address(vault, run, credential)
    assert other != key
    storage[other] = storage[key]  # Even moving valid ciphertext cannot cross the binding.
    assert pending_page.load(redis, vault, other) is None


def test_missing_or_corrupted_cache_is_a_miss(pending, vault):
    _, redis, storage, key = pending
    assert pending_page.load(redis, vault, key) is None
    storage[key] = "invalid"
    assert pending_page.load(redis, vault, key) is None
    storage[key] = vault.seal('{"records":[],"cursor":{},"complete":true}', key)
    assert pending_page.load(redis, vault, key) is None


def test_oversized_page_is_not_cached(pending, vault, monkeypatch):
    _, redis, _, key = pending
    monkeypatch.setattr(pending_page, "MAX_BYTES", 1024)
    assert not pending_page.save(redis, vault, key, {"1": {"text": "x" * 1024}}, Page([], {}, True))
    redis.set.assert_not_called()
