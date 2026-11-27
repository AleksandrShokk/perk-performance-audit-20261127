import csv
from io import StringIO

from sqlalchemy.orm import Session
from test_catalog import card, seed
from test_mobile_supplies_flow import prepare
from test_supply_plans_flow import body, create_url, plan_url
from test_supply_templates_flow import file
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.auth.models import Membership
from app.modules.finance.xlsx import build_template


def empty(s, c):
    response = c.post(create_url(s), json={"title": "Ручной план"})
    assert response.status_code == 201, response.text
    plan = response.json()
    assert not plan["items"] and plan["quantity"] == 0 and plan["revision"] == 1
    return plan, plan_url(s, plan["id"])


def test_empty_create_explicit_selection_remove_and_delete(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan, url = empty(s, c)
    choices = c.get(url + "/products").json()
    assert choices["count"] == 4
    chosen = choices["items"][0]
    result = c.post(
        url + "/products", json={"revision": 1, "product_keys": [chosen["product_key"]]}
    )
    assert result.status_code == 200, result.text
    selected = result.json()
    assert len(selected["items"]) == 1 and selected["quantity"] == 0
    assert (
        c.post(url + "/products", json={"revision": 1, "product_keys": ["wrong"]}).status_code
        == 409
    )
    renamed = c.put(url, json=body(selected, title="Мой план", items=[]))
    assert renamed.status_code == 200 and renamed.json()["title"] == "Мой план"
    assert renamed.json()["items"] == []
    assert c.delete(url, params={"revision": 1}).status_code == 409
    assert c.delete(url, params={"revision": renamed.json()["revision"]}).status_code == 204
    assert c.get(url).status_code == 404


def test_unknown_file_article_reports_file_row_count_and_keeps_plan_unchanged(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan, url = empty(s, c)
    raw = build_template(
        ["артикул", "имя (необязательно)", "количество"],
        [["CHOHO_525SX2_120L_GOLD", "", 10]],
        sheet_name="Поставка",
        numeric=True,
    )
    response = c.post(url + "/import", params={"revision": 1}, files=file(raw))
    assert response.status_code == 422, response.text
    assert "товары из файла: 1" in response.text and "CHOHO_525SX2_120L_GOLD" in response.text
    assert "строка 2" in response.text
    assert c.get(url).json() == plan


def test_barcode_file_adds_only_requested_native_size_and_is_atomic(setup, owner_client):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [("42", card(barcodes=["unique-42-M"]))])
    _, url = empty(s, c)
    item = c.get(url + "/products").json()["items"][0]
    barcode = item["variants"][0]["barcodes"][0]
    raw = build_template(["Баркод", "Количество"], [[barcode, 10]], numeric=True)
    response = c.post(url + "/import", params={"revision": 1}, files=file(raw))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["quantity"] == 10 and len(saved["items"]) == 1
    assert saved["allocation_complete"]
    assert saved["items"][0]["variants"][0]["quantity"] == 10
    bad = build_template(["Баркод", "Количество"], [[barcode, 5], ["missing", 1]], numeric=True)
    assert (
        c.post(url + "/import", params={"revision": saved["revision"]}, files=file(bad)).status_code
        == 422
    )
    assert c.get(url).json() == saved


def test_viewer_cannot_add_import_or_delete(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    _, url = empty(s, c)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions = "viewer", ["inventory.read"]
    assert c.post(url + "/products", json={"revision": 1, "product_keys": ["42"]}).status_code in {
        403,
        404,
    }
    raw = build_template(["Баркод", "Количество"], [["unknown", 10]], numeric=True)
    assert c.post(url + "/import", params={"revision": 1}, files=file(raw)).status_code in {
        403,
        404,
    }
    assert c.delete(url, params={"revision": 1}).status_code in {403, 404}


def test_sizes_export_keeps_explicit_event_dates_and_exact_size(setup, owner_client):
    from datetime import timedelta

    from app.modules.sync.schemas import moscow_today

    s, c = setup, owner_client[0]
    day = str(moscow_today() - timedelta(days=2))
    seed(
        s,
        Source.ORDERS,
        [
            (
                "order",
                {
                    "nm_id": "42",
                    "vendor_code": "boots",
                    "date": day,
                    "last_change_date": day,
                    "barcode": "size-43",
                    "size": "43",
                    "is_cancel": False,
                    "finished_price": "1000",
                    "price_with_discount": "1200",
                },
            )
        ],
    )
    seed(
        s,
        Source.SALES,
        [
            (
                "S1",
                {
                    "nm_id": "42",
                    "vendor_code": "boots",
                    "date": day,
                    "last_change_date": day,
                    "barcode": "size-43",
                    "size": "43",
                    "kind": "sale",
                    "finished_price": "1000",
                    "price_with_discount": "1200",
                },
            )
        ],
    )
    path = f"/api/v1/workspaces/{s.workspace_id}/insights/funnel/export"
    response = c.get(
        path, params={"date_from": day, "date_to": day, "format": "csv", "granularity": "sizes"}
    )
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 1 and rows[0]["Размер"] == "43"
    assert rows[0]["Заказы по дате заказа, шт."] == "1"
    assert rows[0]["Выкупы по дате продажи, шт."] == "1"
    assert "no-store" in response.headers["cache-control"]
