import json
from unittest.mock import Mock

import httpx
import pytest

from app.integrations.ozon.checkpoint import StockCoverCheckpoint
from app.integrations.ozon.operations import OperationsClient
from app.integrations.ozon.transport import OzonImportError


def cache():
    values = {}
    redis = Mock()
    redis.get.side_effect = lambda key: values.get(key)
    redis.set.side_effect = lambda key, value, **kwargs: values.__setitem__(key, value)
    redis.delete.side_effect = lambda key: values.pop(key, None)
    return redis, values


def test_rate_limit_resumes_remaining_skus_and_checkpoint_contains_no_plain_seller_data(vault):
    redis, values = cache()
    checkpoint = StockCoverCheckpoint(
        redis, vault, "workspace", "store", "client", "synthetic-secret"
    )
    calls = []
    fail = True

    def transport(request):
        selected = json.loads(request.content)["skus"]
        calls.append(selected)
        if selected[0] == "101" and fail:
            return httpx.Response(429, headers={"Retry-After": "60"})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "sku": int(sku),
                        "warehouse_id": 1,
                        "cluster_id": 1,
                        "placement_zone": "SORT",
                        "available_stock_count": 10,
                        "ads": 1,
                        "idc": 10,
                        "turnover_grade": "ACTUAL",
                        "name": "private-product-name",
                    }
                    for sku in selected
                ]
            },
        )

    skus = [str(index) for index in range(1, 151)]
    client = OperationsClient(
        "client",
        "synthetic-secret",
        transport=httpx.MockTransport(transport),
        checkpoint=checkpoint,
        pause=lambda _: None,
    )
    with pytest.raises(OzonImportError):
        client.stock_cover(skus)
    assert len(checkpoint.load(skus)["completed"]) == 100
    assert all(
        "private-product-name" not in value and "synthetic-secret" not in value
        for value in values.values()
    )
    fail = False
    rows = client.stock_cover(skus)
    assert len(rows) == 150 and calls[-1][0] == "101"
    assert sum(selected[0] == "1" for selected in calls) == 1
    assert all("name" not in row for row in rows)
    checkpoint.clear()
    assert not values


def test_checkpoint_is_isolated_by_tenant_key_and_sku_set(vault):
    redis, _ = cache()
    first = StockCoverCheckpoint(redis, vault, "workspace", "store", "client", "key-1")
    first.load(["1"])
    first.save({"completed": ["1"], "rows": []})
    for workspace, store, key, skus in [
        ("other", "store", "key-1", ["1"]),
        ("workspace", "other", "key-1", ["1"]),
        ("workspace", "store", "key-2", ["1"]),
        ("workspace", "store", "key-1", ["2"]),
    ]:
        reader = StockCoverCheckpoint(redis, vault, workspace, store, "client", key)
        assert reader.load(skus) == {"completed": [], "rows": []}
    assert redis.set.call_args.kwargs["ex"] == 1800


def test_supply_checkpoint_never_reads_or_clears_stock_cover_checkpoint(vault):
    redis, values = cache()
    cover = StockCoverCheckpoint(redis, vault, "w", "s", "c", "k")
    cover.load(["2026-10-01"])
    cover.save({"completed": ["2026-10-01"], "rows": []})
    supplies = StockCoverCheckpoint(redis, vault, "w", "s", "c", "k", namespace="supplies")
    assert supplies.load(["2026-10-01"]) == {"completed": [], "rows": []}
    supplies.save({"completed": [], "rows": [{"external_id": "ozon:1:2"}]})
    supplies.clear()
    assert len(values) == 1
    assert cover.load(["2026-10-01"])["completed"] == ["2026-10-01"]
