from supply_plan_helpers import select_recommendations
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_connection import ozon as ozon
from test_supply_planner_ozon import (
    test_ozon_uses_custom_cover_and_its_native_identity_for_saved_packaging as prepare_ozon,
)


def test_ozon_plan_preserves_native_product_identity_and_box_multiple(ozon):
    e = ozon
    prepare_ozon(e)
    report = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/replenishment", headers=e.headers
    ).json()
    item = report["items"][0]
    url = f"/api/v1/workspaces/{e.workspace}/stores/{item['store_id']}/inventory/plans"
    response = e.client.post(
        url,
        headers=e.headers,
        json={"title": "Ozon FBO", "destination": "Москва", "target_days": 60, "lead_time_days": 0},
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    plan = select_recommendations(
        e.client, f"/api/v1/workspaces/{e.workspace}/inventory/plans/{plan['id']}", plan, e.headers
    )
    assert plan["quantity"] == 114 and plan["marketplace"] == "ozon"
    assert plan["items"][0]["product_key"] == item["id"]
    assert plan["items"][0]["nm_id"] == "" and plan["items"][0]["box_multiple"] == 6
    export = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/plans/{plan['id']}/export", headers=e.headers
    )
    assert export.status_code == 200 and b"Ozon" in export.content
