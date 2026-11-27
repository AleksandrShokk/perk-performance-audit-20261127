from unittest.mock import Mock

from supply_calendar_helpers import publish_orders
from supply_plan_helpers import select_recommendations
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import queue
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_operations import stock_row

from app.modules.insights.ozon_jobs import execute


def publish(e, sid, stock=20):
    run, _ = queue(e, sid, "stock_cover")
    rows = [
        dict(
            stock_row(sku=101, available=stock, ads="5"),
            ads_cluster="2",
            cluster_id=11,
            cluster_name="Москва",
        ),
        dict(
            stock_row(sku=101, warehouse=2, available=0, ads="5"),
            ads_cluster="3",
            cluster_id=22,
            cluster_name="Санкт-Петербург",
        ),
    ]
    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "stock_cover",
        e.owner,
        run,
        lambda cid, key: Mock(stock_cover=Mock(return_value=rows)),
    )


def test_ozon_native_cluster_demand_remains_independent_from_global_stock_and_ads(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    publish_orders(e, sid, {"101": 140}, {})
    publish(e, sid)
    root = f"/api/v1/workspaces/{e.workspace}/inventory/replenishment"
    params = {"store_id": str(sid), "lead_time_days": 0}
    summary = e.client.get(root + "/destinations", params=params, headers=e.headers)
    assert summary.status_code == 200, summary.text
    items = {r["id"]: r for r in summary.json()["items"]}
    assert items["11"]["recommended_units"] == 40 and items["22"]["recommended_units"] == 90
    report = e.client.get(root, params=params | {"destination_id": "11"}, headers=e.headers).json()
    item = report["items"][0]
    assert item["daily_orders"] == "2" and item["stock"] == 20 and item["quantity"] == 40
    plan = e.client.post(
        f"/api/v1/workspaces/{e.workspace}/stores/{sid}/inventory/plans",
        json={"title": "Москва", "destination_id": "11", "lead_time_days": 0},
        headers=e.headers,
    )
    assert plan.status_code == 201, plan.text
    data = select_recommendations(
        e.client,
        f"/api/v1/workspaces/{e.workspace}/inventory/plans/{plan.json()['id']}",
        plan.json(),
        e.headers,
    )
    assert data["destination"] == "Москва" and data["quantity"] == 40
    publish(e, sid, stock=200)
    combined = e.client.get(root, params=params, headers=e.headers).json()
    regional = e.client.get(
        root, params=params | {"destination_id": "22"}, headers=e.headers
    ).json()
    assert combined["recommended_units"] == 142 and regional["recommended_units"] == 90


def test_native_incoming_is_deducted_only_from_its_destination_cluster(ozon):
    import json

    from sqlalchemy.orm import Session

    from app.modules.auth.dependencies import now
    from app.modules.insights.extra_jobs import aad
    from app.modules.insights.extra_models import MarketplaceSupplySnapshot
    from app.modules.sync.schemas import moscow_today

    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    publish_orders(e, sid, {"101": 140}, {})
    publish(e, sid)
    payload = {
        "items": [
            {
                "marketplace": "ozon",
                "status": "ready_to_ship",
                "warehouse_id": "2",
                "planned_date": str(moscow_today()),
                "goods_complete": True,
                "goods": [{"product_key": "101", "quantity": 20}],
            }
        ]
    }
    with Session(e.admin) as db, db.begin():
        db.add(
            MarketplaceSupplySnapshot(
                workspace_id=e.workspace,
                store_id=sid,
                ciphertext=e.vault.seal(json.dumps(payload), aad(e.workspace, sid, "supplies")),
                updated_at=now(),
            )
        )
    root = f"/api/v1/workspaces/{e.workspace}/inventory/replenishment"
    params = {"store_id": str(sid), "lead_time_days": 0}
    moscow = e.client.get(root, params=params | {"destination_id": "11"}, headers=e.headers).json()
    petersburg = e.client.get(
        root, params=params | {"destination_id": "22"}, headers=e.headers
    ).json()
    assert moscow["recommended_units"] == 40 and moscow["items"][0]["incoming_quantity"] == 0
    assert (
        petersburg["recommended_units"] == 70 and petersburg["items"][0]["incoming_quantity"] == 20
    )
