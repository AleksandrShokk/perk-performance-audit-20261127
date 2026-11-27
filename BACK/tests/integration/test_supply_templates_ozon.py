import pytest
from supply_plan_helpers import select_recommendations
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_connection import ozon as ozon
from test_supply_planner_ozon import (
    test_ozon_uses_custom_cover_and_its_native_identity_for_saved_packaging as prepare_ozon,
)
from test_supply_templates import template, values
from test_supply_templates_flow import file


@pytest.mark.parametrize(
    "kind,header,expected", [("fbo_sku", "SKU", "101"), ("vendor_code", "Артикул", "Article-1")]
)
def test_ozon_uses_native_fbo_sku_or_exact_offer_id_in_uploaded_template(
    ozon, kind, header, expected
):
    e = ozon
    prepare_ozon(e)
    base = f"/api/v1/workspaces/{e.workspace}"
    item = e.client.get(base + "/inventory/replenishment", headers=e.headers).json()["items"][0]
    response = e.client.post(
        base + f"/stores/{item['store_id']}/inventory/plans",
        json={"title": "Ozon"},
        headers=e.headers,
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    plan = select_recommendations(
        e.client, f"/api/v1/workspaces/{e.workspace}/inventory/plans/{plan['id']}", plan, e.headers
    )
    raw = template(headers=(header, "Количество"))
    url = base + f"/inventory/plans/{plan['id']}/template"
    inspected = e.client.post(url + "/inspect", files=file(raw), headers=e.headers)
    assert inspected.status_code == 200, inspected.text
    meta = inspected.json()
    assert meta["suggested"]["identifier_type"] == kind
    choice = next(row for row in meta["choices"] if row["value"] == kind)
    assert choice["preview"][0]["identifier"] == expected
    params = {
        **meta["suggested"],
        "revision": meta["revision"],
        "digest": meta["digest"],
        "data_digest": choice["data_digest"],
    }
    filled = e.client.post(url + "/fill", params=params, files=file(raw), headers=e.headers)
    assert filled.status_code == 200, filled.text
    assert values(filled.content)[2] == {"A": expected, "B": str(plan["quantity"])}
