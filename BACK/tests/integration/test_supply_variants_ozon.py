from supply_plan_helpers import select_recommendations
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_connection import ozon as ozon
from test_supply_planner_ozon import (
    test_ozon_uses_custom_cover_and_its_native_identity_for_saved_packaging as prepare_ozon,
)


def test_ozon_size_uses_native_identity_and_allows_one_selected_barcode(ozon):
    e = ozon
    prepare_ozon(e)
    base = f"/api/v1/workspaces/{e.workspace}"
    item = e.client.get(base + "/inventory/replenishment", headers=e.headers).json()["items"][0]
    response = e.client.post(
        base + f"/stores/{item['store_id']}/inventory/plans",
        headers=e.headers,
        json={"title": "Ozon"},
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    plan = select_recommendations(
        e.client, f"/api/v1/workspaces/{e.workspace}/inventory/plans/{plan['id']}", plan, e.headers
    )
    variant = plan["items"][0]["variants"][0]
    product = next(
        p
        for p in e.client.get(base + "/products", headers=e.headers).json()["items"]
        if p["id"] == item["id"]
    )
    assert variant["variant_id"] == product["variants"][0]["id"]
    assert variant["quantity"] == plan["quantity"]
    data = {
        "revision": plan["revision"],
        "title": plan["title"],
        "destination": "",
        "status": "draft",
        "items": [
            {
                "product_key": item["id"],
                "quantity": plan["quantity"],
                "variants": [
                    {
                        "variant_id": variant["variant_id"],
                        "quantity": plan["quantity"],
                        "barcode": variant["barcodes"][0],
                    }
                ],
            }
        ],
    }
    url = base + f"/inventory/plans/{plan['id']}"
    saved = e.client.put(url, headers=e.headers, json=data)
    assert saved.status_code == 200, saved.text
    assert saved.json()["allocation_complete"]
    export = e.client.get(url + "/items-export", headers=e.headers)
    assert export.status_code == 200 and b"Ozon" in export.content
