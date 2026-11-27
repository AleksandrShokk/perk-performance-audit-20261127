from unittest.mock import Mock

from supply_calendar_helpers import publish_orders
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import queue
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_operations import stock_row

from app.modules.insights.ozon_jobs import execute


def test_ozon_uses_custom_cover_and_its_native_identity_for_saved_packaging(ozon):
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
    report = f"/api/v1/workspaces/{e.workspace}/inventory/replenishment"
    params = {"store_id": str(sid), "target_days": 60, "lead_time_days": 0}
    response = e.client.get(report, params=params, headers=e.headers)
    assert response.status_code == 200, response.text
    first = response.json()["items"][0]
    assert first["quantity"] == 112 and first["nm_id"] == ""
    target = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/inventory/packaging/{first['id']}"
    saved = e.client.put(target, json={"box_multiple": 6}, headers=e.headers)
    assert saved.status_code == 200, saved.text
    data = e.client.get(report, params=params, headers=e.headers).json()
    assert data["recommended_units"] == 114
    assert data["items"][0]["box_multiple"] == 6
    assert data["items"][0]["required_quantity"] == 112
    assert data["items"][0]["marketplace_code"] == first["marketplace_code"]
