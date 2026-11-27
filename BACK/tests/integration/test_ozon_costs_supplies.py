from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import queue
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_finance import accrual
from test_ozon_finance_flow import publish as publish_finance
from test_ozon_operations import stock_row

from app.db.session import set_actor
from app.modules.auth.models import Membership
from app.modules.catalog.identifiers import product_key, variant_key
from app.modules.finance.marketplace_models import MarketplaceVariantCost
from app.modules.finance.ozon_jobs import execute as execute_finance
from app.modules.insights.ozon_jobs import execute as execute_analytics
from app.modules.inventory.settings_models import InventorySettings
from app.modules.sync.schemas import moscow_today


def vid(sid, pid=1):
    return variant_key(product_key(sid, "ozon", str(pid)), str(pid))


def cost(e, sid, amount="100", effective=None, headers=None, variant=None):
    return e.client.put(
        f"/api/v1/workspaces/{e.workspace}/stores/{sid}/variant-costs",
        json={
            "variant_id": variant or vid(sid),
            "amount": amount,
            "currency": "RUB",
            "effective_from": str(effective or moscow_today() - timedelta(days=365)),
        },
        headers=headers or e.headers,
    )


def report(e, sid, start, end, headers=None):
    response = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/finance/overview",
        params={"store_id": str(sid), "date_from": str(start), "date_to": str(end)},
        headers=headers or e.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ozon_variant_cost_updates_catalog_inventory_and_financial_profit(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    result = cost(e, sid)
    assert result.status_code == 200, result.text
    assert result.json()["variant_id"] == vid(sid)
    start, end = publish_finance(e, sid)
    finance = report(e, sid, start, end)
    assert finance["totals"]["profit_before_tax"] == "650.00"
    assert finance["totals"]["expenses_before_tax"] == "350.00"
    assert not finance["expenses_exclude_cogs"]
    assert next(g["amount"] for g in finance["groups"] if g["key"] == "cogs") == "100.00"
    products = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/products",
        params={"store_id": str(sid)},
        headers=e.headers,
    ).json()
    assert products["missing_cost_variants"] == 2
    first = next(p for p in products["items"] if p["external_id"] == "1")
    assert Decimal(first["variants"][0]["unit_cost"]) == 100
    inventory = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/overview",
        params={"store_id": str(sid)},
        headers=e.headers,
    ).json()
    assert inventory["fbo"]["cost_value"] == "800.00" and inventory["fbs"]["cost_value"] == "200.00"
    assert not inventory["total"]["cost_complete"]


def test_costs_never_leak_to_finance_only_reader_or_another_store(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    assert cost(e, sid).status_code == 200
    start, end = publish_finance(e, sid)
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).permissions = ["finance.read", "inventory.read"]
    headers = e.login(e.viewer)
    finance = report(e, sid, start, end, headers)
    assert finance["totals"]["profit_before_tax"] is None
    assert finance["totals"]["expenses_before_tax"] == "250.00"
    assert all(g["key"] != "cogs" for g in finance["groups"])
    history = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/variant-costs"
    assert e.client.get(history, headers=headers).status_code == 403
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.viewer)
        assert (
            db.scalar(select(MarketplaceVariantCost).where(MarketplaceVariantCost.store_id == sid))
            is None
        )
    assert cost(e, sid, variant=str(uuid4())).status_code == 404
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.permissions = ["finance.read", "profit.read", "costs.write"]
        member.store_ids = [str(e.store)]
    assert e.client.get(history, headers=headers).status_code == 404
    assert cost(e, sid, headers=headers).status_code == 404


def test_cost_versions_are_dated_and_repeat_save_is_idempotent(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    old = moscow_today() - timedelta(days=60)
    assert cost(e, sid, "80", old).status_code == 200
    assert cost(e, sid, "80", old).status_code == 200
    assert cost(e, sid, "200", moscow_today()).status_code == 200
    response = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/stores/{sid}/variant-costs",
        params={"variant_id": vid(sid)},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    assert len(response.json()) == 2
    start, end = publish_finance(e, sid)
    assert report(e, sid, start, end)["totals"]["profit_before_tax"] == "670.00"
    with Session(e.admin) as db:
        rows = db.scalars(
            select(MarketplaceVariantCost).where(MarketplaceVariantCost.store_id == sid)
        ).all()
        assert all(row.ciphertext not in ("80", "200") for row in rows)


def test_return_reverses_original_cost_instead_of_current_cost(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    run, (start, end) = queue(e, sid, "finance")
    assert cost(e, sid, "80", start - timedelta(days=10)).status_code == 200
    assert cost(e, sid, "200", end).status_code == 200

    def days(left, right, normalize, progress):
        sold = accrual(sale="2000", commission="-400", quantity=2)
        sold["date"] = str(end - timedelta(days=1))
        returned = accrual(rid=2, sale="-1000", commission="200", price="-700")
        returned["date"] = str(end)
        rows = [sold, returned]
        result = {
            day: normalize([r for r in rows if r["date"] == str(day)], day, {})
            for day in (start + timedelta(days=i) for i in range((end - start).days + 1))
        }
        return result, 2

    execute_finance(
        e.engine, e.vault, e.workspace, sid, e.owner, run, lambda cid, key: Mock(days=days)
    )
    finance = report(e, sid, start, end)
    assert next(g["amount"] for g in finance["groups"] if g["key"] == "cogs") == "80.00"
    assert finance["totals"]["profit_before_tax"] == "620.00"


def test_external_expense_changes_profit_once_without_changing_ozon_settlement(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    assert cost(e, sid).status_code == 200
    start, end = publish_finance(e, sid)
    request_id = str(uuid4())
    path = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/expenses"
    body = {
        "request_id": request_id,
        "expense_date": str(end),
        "amount": "50",
        "currency": "RUB",
        "comment": "Packing",
        "category": "packaging",
    }
    for _ in range(2):
        response = e.client.post(path, json=body, headers=e.headers)
        assert response.status_code == 201, response.text
    finance = report(e, sid, start, end)
    assert finance["totals"]["profit_before_tax"] == "600.00"
    assert finance["totals"]["expenses_before_tax"] == "400.00"
    assert finance["totals"]["settlement"] == "750.00"
    assert e.client.delete(path + "/" + request_id, headers=e.headers).status_code == 204
    assert report(e, sid, start, end)["totals"]["profit_before_tax"] == "650.00"


def test_explicit_fbs_setting_controls_combined_inventory_and_requires_admin(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    path = f"/api/v1/workspaces/{e.workspace}/inventory/settings"
    assert e.client.get(path, headers=e.headers).json()["fbs_mode"] == "unknown"
    assert e.client.put(path, json={"fbs_mode": "separate"}, headers=e.headers).status_code == 200
    overview = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/overview", headers=e.headers
    ).json()
    assert overview["aggregation_status"] == "ready"
    assert overview["fbs"]["retail_value"] is not None
    assert overview["total"]["retail_value"] is not None
    assert e.client.put(path, json={"fbs_mode": "shared"}, headers=e.headers).status_code == 200
    overview = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/overview", headers=e.headers
    ).json()
    assert (
        overview["aggregation_status"] == "warehouse_mapping_required"
        and overview["fbs"]["units"] is None
    )
    headers = e.login(e.viewer)
    assert e.client.put(path, json={"fbs_mode": "separate"}, headers=headers).status_code in {
        403,
        404,
    }
    with Session(e.admin) as db:
        assert db.get(InventorySettings, e.workspace).fbs_mode == "shared"


def test_ozon_replenishment_uses_native_fbo_demand_and_neutral_product_id(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    from supply_calendar_helpers import publish_orders

    publish_orders(e, sid, {"101": 56}, {})
    run, _ = queue(e, sid, "stock_cover")
    source = Mock(
        stock_cover=Mock(return_value=[stock_row(sku=101, available=8, ads="2", idc="4")])
    )
    execute_analytics(
        e.engine, e.vault, e.workspace, sid, "stock_cover", e.owner, run, lambda cid, key: source
    )
    response = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/replenishment",
        params={"store_id": str(sid), "limit": 30},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["recommended_units"] == 60 and data["urgent_count"] == 1
    first = data["items"][0]
    assert first["demand_basis"] == "ozon_orders" and first["daily_orders"] == "2"
    assert first["stock"] == 8 and first["quantity"] == 60
    assert first["id"] and first["nm_id"] == "" and first["marketplace"] == "ozon"
