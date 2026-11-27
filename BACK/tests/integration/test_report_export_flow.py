from datetime import timedelta
from io import BytesIO
from unittest.mock import Mock
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import publish as publish_sales
from test_ozon_analytics_flow import queue
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_finance_flow import publish as publish_finance

from app.modules.auth.models import Membership
from app.modules.insights.ozon_jobs import execute

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def workbook(content):
    with ZipFile(BytesIO(content)) as book:
        names = [
            node.attrib["name"]
            for node in ET.fromstring(book.read("xl/workbook.xml")).findall("m:sheets/m:sheet", NS)
        ]
        sheets = []
        for index in range(1, len(names) + 1):
            root = ET.fromstring(book.read(f"xl/worksheets/sheet{index}.xml"))
            rows = []
            for row in root.findall("m:sheetData/m:row", NS):
                rows.append(["".join(cell.itertext()) for cell in row])
            sheets.append(rows)
    return dict(zip(names, sheets, strict=True))


def test_finance_export_has_nested_lines_and_scoped_cabinet_sheets(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish_finance(e, sid)
    path = f"/api/v1/workspaces/{e.workspace}/finance/export"
    params = {"date_from": str(start), "date_to": str(end)}
    response = e.client.get(path, params=params, headers=e.headers)
    assert response.status_code == 200, response.text
    sheets = workbook(response.content)
    assert len(sheets) == 3 and "Сводка" in sheets
    ozon_rows = next(rows for name, rows in sheets.items() if name.startswith("Ozon "))
    assert any(row[3] == "К перечислению" and row[4] == "750.00" for row in ozon_rows[1:])
    assert len(ozon_rows) > 20 and any(
        row[2] == "Логистика" and row[3] != "Итого по разделу" for row in ozon_rows[1:]
    )
    csv = e.client.get(path, params={**params, "format": "csv"}, headers=e.headers)
    assert csv.status_code == 200 and "Ozon synthetic" in csv.content.decode("utf-8-sig")
    assert e.ozon_key not in csv.text
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.role = "manager"
        member.permissions = ["finance.read", "reports.export"]
        member.store_ids = [str(sid)]
    viewer = e.login(e.viewer)
    response = e.client.get(path, params=params, headers=viewer)
    assert response.status_code == 200, response.text
    restricted = workbook(response.content)
    assert len(restricted) == 1
    assert not any(row[2] == "Себестоимость" for rows in restricted.values() for row in rows[1:])
    assert (
        e.client.get(path, params={**params, "store_id": str(e.store)}, headers=viewer).status_code
        == 404
    )
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).permissions = ["finance.read"]
    assert e.client.get(path, params=params, headers=viewer).status_code == 403


def test_inventory_export_contains_all_native_rows_and_marketplace_sheets(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    path = f"/api/v1/workspaces/{e.workspace}/inventory/export"
    response = e.client.get(path, headers=e.headers)
    assert response.status_code == 200, response.text
    sheets = workbook(response.content)
    assert set(sheets) == {"Общие остатки", "Сводка", "WB", "Ozon"}
    assert len(sheets["Общие остатки"]) - 1 == sum(len(sheets[name]) - 1 for name in ["WB", "Ozon"])
    assert all(row[1] == "WB" for row in sheets["WB"][1:])
    assert all(row[1] == "Ozon" for row in sheets["Ozon"][1:])
    assert e.ozon_key not in response.content.decode("latin-1")
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.role = "manager"
        member.permissions = ["inventory.read", "reports.export"]
        member.store_ids = [str(sid)]
    viewer = e.login(e.viewer)
    response = e.client.get(path, headers=viewer)
    assert response.status_code == 200, response.text
    sheets = workbook(response.content)
    assert "WB" not in sheets
    assert not any("себестоим" in cell.lower() for cell in sheets["Общие остатки"][0])
    assert e.client.get(path, params={"store_id": str(e.store)}, headers=viewer).status_code == 404
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).permissions = ["inventory.read"]
    assert e.client.get(path, headers=viewer).status_code == 403


def test_ozon_sku_traffic_reaches_api_and_file_without_changing_order_sums(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    start, end = publish_sales(e, sid)
    path = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    params = {"date_from": str(start), "date_to": str(end)}
    before = e.client.get(path, params=params, headers=e.headers).json()
    run, _ = queue(e, sid, "traffic")
    days = {
        start + timedelta(days=index): {
            "impressions": 1000,
            "opens": 100,
            "carts": 20,
            "version": 2,
            "products": {"101": {"impressions": 1000, "opens": 100, "carts": 20}},
        }
        for index in range(7)
    }
    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "traffic",
        e.owner,
        run,
        lambda cid, key: Mock(days=lambda *args: days),
    )
    response = e.client.get(path, params=params, headers=e.headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["totals"]["orders_amount"] == before["totals"]["orders_amount"]
    assert data["totals"]["impressions"] == 7000 and data["totals"]["add_to_cart_percent"] == "20.0"
    assert data["product_traffic_known_days"] == 7
    product = next(row for row in data["products"] if row["marketplace_code"] == "101")
    assert product["opens"] == 700 and product["carts"] == 140 and product["id"]
    for granularity in ["products", "days"]:
        result = e.client.get(
            f"/api/v1/workspaces/{e.workspace}/insights/funnel/export",
            params={**params, "store_id": str(sid), "granularity": granularity},
            headers=e.headers,
        )
        assert result.status_code == 200, result.text
        rows = workbook(result.content)["Аналитика"]
        column = rows[0].index("Показы")
        assert sum(int(row[column]) for row in rows[1:] if row[column]) == 7000
