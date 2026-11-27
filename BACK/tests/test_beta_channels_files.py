import json
from datetime import date
from decimal import Decimal

import httpx
from test_stock_cover import wb_row
from test_supply_destinations import office

from app.integrations.wildberries.data import Source, WBDataClient
from app.modules.finance.xlsx import build_template, read_rows
from app.modules.inventory.channel_cover import channel_position, channel_total
from app.modules.supplies.destinations.normalize import wb_regions


def test_wb_fbs_coverage_uses_its_own_native_channel():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"items": [wb_row()]}})

    client = WBDataClient(httpx.MockTransport(handler))
    client.page(Source.SUPPLY_DEMAND_FBS, "synthetic", {}, date(2026, 10, 1), date(2026, 10, 28))
    assert seen[0]["stockType"] == "mp"


def test_native_wb_aggregate_buckets_are_not_presented_as_warehouses():
    row = {**office(-999999), "officeName": "Склад WB РФ"}
    assert wb_regions({"offices": [row]}, date(2026, 10, 1), date(2026, 10, 28)) == []


def test_two_real_warehouses_are_not_merged_just_because_the_region_matches():
    rows = [{**office(1), "officeName": "Коледино"}, {**office(2), "officeName": "Подольск"}]
    result = wb_regions({"offices": rows}, date(2026, 10, 1), date(2026, 10, 28))
    assert {row["name"] for row in result} == {"Коледино", "Подольск"}
    assert len({row["id"] for row in result}) == 2


def test_channel_stock_uses_matching_demand_and_never_turns_missing_demand_into_zero():
    assert channel_position(10, Decimal(2)) == ("5.00", "ready")
    assert channel_position(10, Decimal(0)) == (None, "no_orders")
    assert channel_position(10, None) == (None, "no_data")
    assert channel_total([(10, Decimal(2)), (30, Decimal(3))]) == ("8.00", False)
    assert channel_total([(10, Decimal(2)), (30, None)]) == ("5.00", True)


def test_xlsx_export_keeps_identifiers_as_text_and_does_not_create_formula_cells():
    headers = ("Артикул", "Количество")
    rows = [["000000123456789012345", 5], ["=1+1", 6]]
    payload = build_template(headers, rows, sheet_name="Экспорт", numeric=True)
    assert read_rows(payload, headers=headers, sheet_name="Экспорт") == [
        (2, ["000000123456789012345", "5"]),
        (3, ["=1+1", "6"]),
    ]
