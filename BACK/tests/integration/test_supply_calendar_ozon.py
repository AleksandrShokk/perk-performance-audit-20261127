from unittest.mock import Mock

from supply_calendar_helpers import publish_orders
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_catalog import payload
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon

from app.modules.supplies.destinations.service import reports


def test_actual_fbo_and_fbs_orders_sum_by_native_sku_without_adjusted_ads(ozon):
    e = ozon
    sid = connect(e)
    row = payload()
    row["channels"]["fbo"]["quantity"] = 0
    row["channels"]["fbs"]["quantity"] = 5
    publish_catalog(e, sid, [row])
    publish_orders(e, sid, {"101": 13}, {"201": 5})
    url = f"/api/v1/workspaces/{e.workspace}/inventory/replenishment"
    args = {"store_id": str(sid)}
    plain = e.client.get(url, params=args, headers=e.headers)
    assert plain.status_code == 200, plain.text
    assert plain.json()["items"][0]["quantity"] == 20
    reduced = e.client.get(url, params=args | {"include_fbs": True}, headers=e.headers).json()
    assert reduced["items"][0]["quantity"] == 15
    assert reduced["items"][0]["fbs_reduction"] == 5


def test_incomplete_ozon_days_stay_unknown_instead_of_adjusted_sales_fallback(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    publish_orders(e, sid, {"101": 18}, {}, days=7)
    response = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/replenishment",
        params={"store_id": str(sid)},
        headers=e.headers,
    )
    assert response.status_code == 200
    assert response.json()["recommended_units"] is None
    assert response.json()["items"] == []


def test_one_fbs_pool_cannot_be_subtracted_from_every_cluster(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.modules.supplies.destinations import service

    store = SimpleNamespace(id=uuid4(), name="Ozon", marketplace="ozon")
    key = str(uuid4())
    product = dict(
        id=key,
        marketplace="ozon",
        marketplace_code="101",
        demand_basis="ozon_orders",
        store_id=store.id,
        store_name=store.name,
        nm_id="",
        vendor_code="a",
        title="A",
        photo=None,
        colors=[],
        barcodes=[],
    )
    records = [
        (
            product,
            {"id": str(n), "name": str(n), "warehouse_ids": [], "daily_orders": "1", "stock": 0},
            None,
            ["101"],
        )
        for n in (1, 2)
    ]
    monkeypatch.setattr(service, "ozon_data", lambda *args: (records, 1, 1, False, 0))
    native = Mock(complete=True, current=True, quantities={})
    native.events.return_value = []
    native.quantity.return_value = 0
    native.for_warehouses.return_value = native
    monkeypatch.setattr(service, "incoming_read", lambda *args, **kwargs: native)
    monkeypatch.setattr(service, "multiples", lambda *args: {})
    monkeypatch.setattr(service, "fbs_quantities", lambda *args: {key: 35})
    values, *_ = reports(None, None, uuid4(), [store], lead_time_days=0, include_fbs=True)
    assert sum(r.recommended_units for _, r in values) == 25
    assert sum(i.fbs_reduction for _, r in values for i in r.items) == 5
