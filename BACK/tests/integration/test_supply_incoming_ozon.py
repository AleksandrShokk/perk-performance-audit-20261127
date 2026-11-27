import json
from unittest.mock import Mock

from sqlalchemy.orm import Session
from supply_calendar_helpers import publish_orders
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import queue
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_operations import stock_row

from app.modules.auth.dependencies import now
from app.modules.insights.extra_jobs import aad
from app.modules.insights.extra_models import MarketplaceSupplySnapshot
from app.modules.insights.ozon_jobs import execute
from app.modules.sync.schemas import moscow_today


def test_ozon_maps_incoming_only_by_native_fbo_sku_and_rounds_after_deduction(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    publish_orders(e, sid, {"101": 56}, {})
    run, _ = queue(e, sid, "stock_cover")
    source = Mock(
        stock_cover=Mock(return_value=[stock_row(sku=101, available=8, ads="2", idc="4")])
    )
    execute(
        e.engine, e.vault, e.workspace, sid, "stock_cover", e.owner, run, lambda cid, key: source
    )
    data = {
        "items": [
            {
                "marketplace": "ozon",
                "status": "ready_to_ship",
                "planned_date": str(moscow_today()),
                "goods_complete": True,
                "goods": [
                    {"product_key": "101", "quantity": 20},
                    {"product_key": "201", "quantity": 1000},
                ],
            }
        ]
    }
    with Session(e.admin) as db, db.begin():
        db.add(
            MarketplaceSupplySnapshot(
                workspace_id=e.workspace,
                store_id=sid,
                ciphertext=e.vault.seal(json.dumps(data), aad(e.workspace, sid, "supplies")),
                updated_at=now(),
            )
        )
    path = f"/api/v1/workspaces/{e.workspace}/inventory/replenishment"
    response = e.client.get(path, params={"store_id": str(sid)}, headers=e.headers)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    # 8 existing units sell before arrival; new 60-day demand minus native FBO incoming 20.
    assert item["required_quantity"] == 40 and item["incoming_quantity"] == 20
    assert item["incoming_reduction"] == 20
    packaging = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/inventory/packaging/{item['id']}"
    assert e.client.put(packaging, json={"box_multiple": 6}, headers=e.headers).status_code == 200
    second = e.client.get(path, params={"store_id": str(sid)}, headers=e.headers).json()
    assert second["recommended_units"] == 42 and second["items"][0]["required_quantity"] == 40
