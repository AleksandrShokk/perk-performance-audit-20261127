import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.supplies.incoming import Arrival, Incoming
from app.modules.supplies.service import from_demand
from app.modules.sync.normalize import normalize

TODAY = date(2026, 11, 6)


@pytest.mark.parametrize(
    "stock,events,expected",
    [
        (100, [], 85),
        (100, [Arrival(7, 50)], 35),
        (100, [Arrival(7, 1000)], 0),
        (0, [Arrival(20, 100)], 65),  # Must still cover days 7..20 before the late shipment.
        (0, [Arrival(37, 1000)], 150),
        (0, [Arrival(38, 1000)], 150),
        (0, [Arrival(0, 35)], 150),  # Consumed before the new shipment can arrive.
        (0, [Arrival(3, 100)], 70),
        (100, [Arrival(7, 20), Arrival(7, 30)], 35),
        (100, [Arrival(-1, 1000)], 85),
    ],
)
def test_dated_supplies_reduce_only_demand_they_can_cover(stock, events, expected):
    result = from_demand(stock, Decimal(5), arrivals=events)
    assert result["quantity"] == expected
    baseline = from_demand(stock, Decimal(5))["quantity"]
    assert result["incoming_reduction"] == baseline - expected


def shipment(**changes):
    return dict(
        status="planned",
        planned_date=str(TODAY),
        actual_date=None,
        goods_complete=True,
        goods=[{"product_key": "42", "quantity": 50}],
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "draft"},
        {"status": "accepted"},
        {"status": "cancelled"},
        {"status": "shipped"},
        {"status": "accepting"},
        {"rejected": True},
        {"accepted_quantity": 1},
        {"goods_complete": False},
        {"actual_date": str(TODAY)},
        {"planned_date": str(TODAY - timedelta(days=1))},
        {"planned_date": None},
        {"planned_date": str(TODAY + timedelta(days=31))},
    ],
)
def test_unconfirmed_or_received_goods_never_reduce_recommendations(changes):
    row = {**shipment(), **changes}
    value = Incoming([row], current=True, today=TODAY, lead_time_days=7, target_days=30)
    assert value.events(["42"]) == []


def test_incoming_is_native_product_specific_and_newer_than_stock():
    stamp = datetime.now(UTC)
    value = Incoming(
        [shipment(), {**shipment(), "marketplace": "ozon", "status": "shipped"}],
        current=True,
        today=TODAY,
        lead_time_days=7,
        target_days=30,
        checked_at=stamp,
    )
    assert value.quantity(["42"]) == 100 and value.quantity(["other"]) == 0
    assert value.events(["42"], stamp) == [Arrival(7, 50), Arrival(7, 50)]
    assert not value.events(["42"], stamp + timedelta(seconds=1))
    stale = Incoming([shipment()], current=False, today=TODAY, lead_time_days=7, target_days=30)
    assert stale.quantity(["42"]) is None and not stale.events(["42"])


def wb_transport(*, changed=False, duplicate=False, receiving=False):
    calls, verified = [], 0

    def respond(request):
        nonlocal verified
        calls.append(request)
        if request.method == "POST":
            active = 2 in json.loads(request.content)["statusIDs"]
            return httpx.Response(200, json=[{"supplyID": 8, "preorderID": 7}] if active else [])
        if request.url.path.endswith("/goods"):
            row = {
                "barcode": "001",
                "nmID": 42,
                "quantity": 10,
                "acceptedQuantity": 1 if receiving else 0,
                "private": "NEVER-STORE",
            }
            return httpx.Response(200, json=[row, row] if duplicate else [row])
        verified += 1
        return httpx.Response(
            200,
            json={
                "statusID": 3,
                "quantity": 10,
                "acceptedQuantity": 0,
                "updatedDate": str(verified) if changed else "stable",
                "warehouseName": "WB",
                "phone": "NEVER-STORE",
                "rejectReason": None,
            },
        )

    return httpx.MockTransport(respond), calls


def download(transport):
    client, cursor = WBDataClient(transport), {}
    for _ in range(20):
        page = client.page(Source.SUPPLIES, "synthetic", cursor, None, None)
        assert "NEVER-STORE" not in json.dumps(page.cursor)
        cursor = page.cursor
        if page.complete:
            return normalize(Source.SUPPLIES, page.rows[0])[1]
    raise AssertionError("Import did not finish")


def test_wb_fetches_barcodes_and_rechecks_before_publishing():
    transport, calls = wb_transport()
    row = download(transport)
    assert row["goods_complete"] and row["goods"] == [{"product_key": "42", "quantity": 10}]
    assert len(calls) == 5 and calls[3].url.path == "/api/v1/supplies/8/goods"
    assert all(request.method in {"GET", "POST"} for request in calls)
    assert "NEVER-STORE" not in json.dumps(row)


def test_wb_receiving_goods_are_not_credited():
    transport, _ = wb_transport(receiving=True)
    assert not download(transport)["goods_complete"]


@pytest.mark.parametrize("options", [{"duplicate": True}, {"changed": True}])
def test_wb_duplicate_or_changing_contents_fail_without_publishing(options):
    transport, _ = wb_transport(**options)
    with pytest.raises(WBError):
        download(transport)


def test_goods_subresource_cannot_change_host_or_source():
    with pytest.raises(WBError):
        WBDataClient().request(Source.CATALOG, "synthetic", supply_goods=True)


def test_wb_goods_pages_are_accumulated_before_the_final_verification(monkeypatch):
    from app.integrations.wildberries import supplies

    monkeypatch.setattr(supplies, "PAGE_SIZE", 3)
    offsets = []

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                json=[{"supplyID": 8, "preorderID": 7}]
                if 2 in json.loads(request.content)["statusIDs"]
                else [],
            )
        if request.url.path.endswith("/goods"):
            offset = int(request.url.params["offset"])
            offsets.append(offset)
            return httpx.Response(
                200,
                json=[
                    {"nmID": 42, "quantity": 1, "barcode": str(i)}
                    for i in range(offset, min(offset + 3, 4))
                ],
            )
        return httpx.Response(200, json={"statusID": 2, "quantity": 4, "updatedDate": "same"})

    row = download(httpx.MockTransport(handler))
    assert offsets == [0, 3] and row["goods_complete"]
    assert sum(g["quantity"] for g in row["goods"]) == 4


def test_ozon_retains_native_skus_and_does_not_reuse_old_totals_without_contents():
    from test_ozon_parity import supply_raw

    from app.integrations.ozon.supplies import BUNDLE, COUNTER, GET, LIST, SupplyClient

    calls = []

    def handler(request):
        calls.append(request.url.path)
        values = {
            COUNTER: {"items": [{"order_state": "ORDER_STATE_COMPLETED", "count": 1}]},
            LIST: {"order_ids": [1], "last_id": ""},
            GET: {"orders": [supply_raw()]},
            BUNDLE: {
                "items": [{"sku": 101, "quantity": 5}, {"sku": 102, "quantity": 6}],
                "has_next": False,
            },
        }
        return httpx.Response(200, json=values[request.url.path])

    def load(previous=None):
        return SupplyClient("1", "test", transport=httpx.MockTransport(handler)).snapshot(
            date(2026, 10, 3), previous
        )

    first = load()
    assert first["items"][0]["goods"] == [
        {"product_key": "101", "quantity": 5},
        {"product_key": "102", "quantity": 6},
    ]
    assert first["items"][0]["goods_complete"]
    calls.clear()
    assert load(first)["items"][0]["quantity"] == 11 and BUNDLE not in calls
    first["items"][0].pop("goods_complete")
    calls.clear()
    assert load(first)["items"][0]["goods_complete"] and BUNDLE in calls


def test_ozon_goods_pagination_and_duplicate_skus_are_validated():
    from app.integrations.ozon.supplies import SupplyClient

    calls = []

    def handler(request):
        last = json.loads(request.content)["last_id"]
        calls.append(last)
        return httpx.Response(
            200,
            json={
                "items": [{"sku": 101 if not last else 102, "quantity": 5}],
                "has_next": not last,
                "last_id": "next",
            },
        )

    with SupplyClient("1", "test", transport=httpx.MockTransport(handler)) as client:
        assert client.goods("bundle") == [
            {"product_key": "101", "quantity": 5},
            {"product_key": "102", "quantity": 5},
        ]
    assert calls == ["", "next"]


@pytest.mark.parametrize("days_since_booking,expected", [(1, 6), (6, 1), (7, 0), (8, None)])
def test_ozon_confirmed_transit_uses_remaining_allowance_without_rolling_overdue_eta_forward(
    days_since_booking, expected
):
    row = {
        **shipment(),
        "marketplace": "ozon",
        "status": "shipped",
        "planned_date": str(TODAY - timedelta(days=days_since_booking)),
    }
    value = Incoming([row], current=True, today=TODAY, lead_time_days=7, target_days=30)
    assert value.events(["42"]) == ([] if expected is None else [Arrival(expected, 50)])


def test_recently_verified_supply_is_usable_after_a_long_wb_import():
    stamp = datetime.now(UTC)
    row = {**shipment(), "checked_at": stamp.isoformat()}
    value = Incoming(
        [row],
        current=True,
        today=TODAY,
        lead_time_days=7,
        target_days=30,
        checked_at=stamp - timedelta(hours=3),
    )
    assert value.quantity(["42"]) == 50
    assert value.events(["42"], stamp - timedelta(minutes=1)) == [Arrival(7, 50)]


def test_old_goods_in_a_newly_published_snapshot_do_not_look_fresh():
    stamp = datetime.now(UTC)
    row = {**shipment(), "checked_at": (stamp - timedelta(hours=3)).isoformat()}
    value = Incoming(
        [row], current=True, today=TODAY, lead_time_days=7, target_days=30, checked_at=stamp
    )
    assert not value.complete and value.quantity(["42"]) is None
    assert value.events(["42"]) == []
