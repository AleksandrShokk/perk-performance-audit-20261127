import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from test_stock_cover import report, wb_row

from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.supplies.service import recommendation
from app.modules.sync.normalize import normalize
from app.modules.sync.quota import addresses


@pytest.mark.parametrize(
    "changes,quantity,urgent",
    [
        ({}, 85, False),
        ({"stock": 0}, 150, True),
        ({"stock": 20}, 150, True),
        ({"stock": 200}, 0, False),
        ({"stock": 35}, 150, True),
    ],
)
def test_replenishment_covers_30_days_after_7_day_arrival(changes, quantity, urgent):
    value = recommendation(report(**changes))
    assert value["quantity"] == quantity and value["urgent"] == urgent


@pytest.mark.parametrize(
    "changes",
    [{"orders": 0}, {"orders": None}, {"date_from": "2026-10-02"}, {"stock": None}],
)
def test_unknown_or_zero_demand_never_invents_a_supply(changes):
    assert recommendation(report(**changes)) is None


def test_fbo_demand_uses_its_own_report_but_shares_the_upstream_limit():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"items": [wb_row()]}})

    page = WBDataClient(httpx.MockTransport(respond)).page(
        Source.SUPPLY_DEMAND, "synthetic", {}, date(2026, 10, 1), date(2026, 10, 28)
    )
    assert json.loads(requests[0].content)["stockType"] == "wb"
    assert page.complete and normalize(Source.SUPPLY_DEMAND, page.rows[0])[1] == report()
    vault = SimpleNamespace(digest=lambda *parts: ":".join(parts))
    metadata = SimpleNamespace(seller_id="synthetic", token_type=3)
    assert addresses(vault, Source.SUPPLY_DEMAND, metadata) == addresses(
        vault, Source.STOCK_HISTORY, metadata
    )


def test_read_only_supply_import_paginates_and_never_retains_phone_or_money():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json=[
                    {
                        "supplyID": None,
                        "preorderID": 7,
                        "statusID": 1,
                        "phone": "NEVER-STORE",
                        "createDate": "2026-11-01T00:00:00+03:00",
                    }
                ]
                if 1 in body["statusIDs"]
                else [],
            )
        assert (
            request.url.path == "/api/v1/supplies/7"
            and request.url.params["isPreorderID"] == "true"
        )
        return httpx.Response(
            200,
            json={
                "statusID": 1,
                "quantity": 15,
                "acceptedQuantity": 0,
                "warehouseName": "Пункт отгрузки",
                "phone": "NEVER-STORE",
                "acceptanceCost": 123,
            },
        )

    client = WBDataClient(httpx.MockTransport(respond))
    cursor = {}
    for _ in range(3):
        page = client.page(Source.SUPPLIES, "synthetic", cursor, None, None)
        assert "NEVER-STORE" not in json.dumps(page.cursor)
        cursor = page.cursor
    assert page.complete and len(page.rows) == 1
    key, row = normalize(Source.SUPPLIES, page.rows[0])
    assert key == "p:7" and row["quantity"] == 15 and row["status"] == "draft"
    assert "phone" not in row and "acceptanceCost" not in row
    assert len(requests) == 3


def test_supply_identity_survives_assignment_and_unknown_status_fails_closed():
    base = {"preorderID": 7, "supplyID": 8, "details": {"statusID": 3, "quantity": 0}}
    key, row = normalize(Source.SUPPLIES, base)
    assert key == "p:7" and row["status"] == "ready_to_ship" and row["quantity"] == 0
    with pytest.raises(WBError):
        normalize(Source.SUPPLIES, {**base, "details": {"statusID": 999}})
    with pytest.raises(WBError):
        WBDataClient().request(Source.SUPPLIES, "synthetic", supply="arbitrary/path")
