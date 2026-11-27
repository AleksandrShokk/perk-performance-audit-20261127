from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace as NS
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.modules.finance.export import report_rows
from app.modules.finance.xlsx import build_template, sheet_names
from app.modules.inventory.export import position_row


def finance():
    return NS(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        currency="RUB",
        is_partial=False,
        period_covered=True,
        totals=NS(
            seller_revenue="1000",
            expenses_before_tax="200",
            settlement="800",
            profit_before_tax="700",
        ),
        taxes=NS(vat=None, tax="42", net_profit="658"),
        groups=[
            NS(
                key="logistics",
                title="Логистика",
                amount="100",
                lines=[
                    NS(title="Обратная логистика", amount="25", unit="money"),
                    NS(title="Возмещено", amount="-5", unit="money"),
                    NS(title="Количество", amount="7", unit="units"),
                ],
            ),
            NS(
                key="cogs",
                title="Себестоимость",
                amount="100",
                lines=[NS(title="Закупка", amount="100", unit="money")],
            ),
        ],
    )


def test_finance_has_subitems_units_unknowns_and_line_shares():
    rows = report_rows(finance(), "Магазин", "WB", True)
    reverse = next(row for row in rows if row[3] == "Обратная логистика")
    assert reverse[4] == Decimal(25) and reverse[6] == Decimal("2.5")
    refunded = next(row for row in rows if row[3] == "Возмещено")
    assert refunded[4] == Decimal(-5) and refunded[6] == Decimal("-0.5")
    units = next(row for row in rows if row[3] == "Количество")
    assert units[5] == "шт." and units[6] is None and units[7] == ""
    assert next(row for row in rows if row[3] == "НДС · оценка")[4] is None


def test_finance_without_profit_permission_excludes_costs_taxes_and_profit():
    rows = report_rows(finance(), "Магазин", "WB", False)
    assert not any(
        row[2] == "Себестоимость"
        or row[3] in {"Закупка", "Прибыль до налогов", "Чистая прибыль · оценка", "Налог · оценка"}
        for row in rows
    )
    assert any(row[3] == "К перечислению" for row in rows)


def test_excel_numeric_cells_are_numeric_on_every_sheet_and_identifiers_are_text():
    data = build_template(
        ["Код", "Сумма"],
        [["00101", Decimal("-10.50")]],
        numeric=True,
        extra_sheets=[("Ozon", ["Код", "Сумма"], [["=SUM(A1)", Decimal("20.25")]])],
    )
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(data)) as book:
        for index, amount in [(1, "-10.50"), (2, "20.25")]:
            root = ET.fromstring(book.read(f"xl/worksheets/sheet{index}.xml"))
            assert root.find(".//s:c[@r='B2']", ns).get("t") == "n"
            assert root.find(".//s:c[@r='B2']/s:v", ns).text == amount
            assert root.find(".//s:c[@r='A2']", ns).get("t") == "inlineStr"
            assert root.findall(".//s:f", ns) == []


def test_sheet_names_are_safe_unique_and_within_excel_limit():
    names = sheet_names(
        ["WB / Магазин:*?", "wb / магазин:*?", "Сводка", "'" + "я" * 80], reserved=["Сводка"]
    )
    assert all(len(name) <= 31 and not any(c in name for c in "[]:*?/\\") for name in names)
    assert len({name.casefold() for name in names}) == 4


def position():
    return NS(
        product=NS(
            store_name="Магазин",
            marketplace="ozon",
            vendor_code="00123",
            marketplace_code="123",
            title="Товар",
            colors=["Чёрный"],
            variants=[NS(size="42", barcodes=["000123"])],
        ),
        fbo=NS(units=2, retail_value="200", cost_value="80", cost_complete=True),
        fbs=NS(units=None, retail_value=None, cost_value=None, cost_complete=False),
        turnover_days=None,
        turnover_status="no_orders",
    )


def test_inventory_export_keeps_unknowns_and_cost_access():
    row = position_row(position(), "RUB", False)
    assert row[2] == "00123" and row[7] == "000123"
    assert row[8:12] == [2, Decimal(200), None, None]
    assert Decimal(80) not in row
    with_cost = position_row(position(), "RUB", True)
    assert with_cost[12:15] == [Decimal(80), None, "Нет"]
