from datetime import date
from decimal import Decimal

import pytest
from test_ozon_operations import stock_row

from app.modules.inventory.ozon_cover import normalize
from app.modules.supplies.destinations.normalize import wb_regions
from app.modules.supplies.incoming import Arrival, Incoming

START, END = date(2026, 10, 1), date(2026, 10, 28)


def office(warehouse=1, region="Центр", stock=10, orders=28, missing=None):
    return {
        "officeID": warehouse,
        "regionName": region,
        "officeName": region,
        "metrics": {
            "stockCount": stock,
            "ordersCount": orders,
            "officeMissingTime": missing or {"days": 0, "hours": 0},
        },
    }


def test_wb_never_counts_root_and_size_offices_twice_and_uses_each_variants_availability():
    data = {
        "offices": [office(stock=999, orders=999)],
        "sizes": [
            {"chrtID": 10, "offices": [office(stock=4, orders=28), office(stock=4, orders=28)]},
            {
                "chrtID": 11,
                "offices": [office(stock=6, orders=28, missing={"days": 14, "hours": 0})],
            },
        ],
    }
    group = wb_regions(data, START, END)[0]
    assert group["stock"] == 10 and Decimal(group["daily_orders"]) == 3
    assert group["warehouse_ids"] == ["1"]


def test_wb_regions_are_native_and_have_independent_stock_and_demand():
    groups = wb_regions({"offices": [office(), office(2, "Сибирь", 100, 56)]}, START, END)
    assert len({g["id"] for g in groups}) == 2
    assert groups[0]["daily_orders"] == "1" and groups[1]["daily_orders"] == "2"
    with pytest.raises(ValueError):
        wb_regions({"offices": [office(), office(stock=11)]}, START, END)


def test_unknown_wb_missing_time_does_not_become_zero_or_fabricated_regional_demand():
    group = wb_regions({"offices": [office(missing={"days": 0, "hours": -4})]}, START, END)[0]
    assert group["daily_orders"] is None and group["stock"] == 10
    group = wb_regions({"offices": [office(orders=0)]}, START, END)[0]
    assert group["daily_orders"] == "0"


def test_ozon_cluster_ads_is_not_summed_for_each_warehouse_or_copied_from_global_ads():
    rows = [
        dict(
            stock_row(available=4, ads="10"), ads_cluster="2", cluster_id=11, cluster_name="Москва"
        ),
        dict(
            stock_row(warehouse=2, available=6, ads="10"),
            ads_cluster="2",
            cluster_id=11,
            cluster_name="Москва",
        ),
        dict(stock_row(warehouse=3, available=8, ads="10"), ads_cluster="3", cluster_id=22),
    ]
    facts = normalize(rows)["101"]
    assert facts["ads"] == "1E+1" or Decimal(facts["ads"]) == 10
    groups = {g["id"]: g for g in facts["destinations"]}
    assert groups["11"]["stock"] == 10 and Decimal(groups["11"]["daily_orders"]) == 2
    assert groups["22"]["stock"] == 8 and Decimal(groups["22"]["daily_orders"]) == 3
    assert groups["11"]["warehouse_ids"] == ["1", "2"]


def test_old_ozon_snapshots_do_not_invent_cluster_demand():
    facts = normalize([stock_row()])["101"]
    assert facts["ads"] == "1" and facts["destinations"][0]["daily_orders"] is None


def test_conflicting_cluster_demand_stays_unknown():
    rows = [dict(stock_row(), ads_cluster="2"), dict(stock_row(warehouse=2), ads_cluster="3")]
    assert normalize(rows)["101"]["destinations"][0]["daily_orders"] is None


def test_incoming_is_scoped_by_destination_warehouse_without_name_matching():
    today = date.today()
    rows = [
        dict(
            status="planned",
            planned_date=str(today),
            goods_complete=True,
            warehouse_id=warehouse,
            goods=[{"product_key": "42", "quantity": quantity}],
        )
        for warehouse, quantity in [("1", 20), ("2", 50)]
    ]
    incoming = Incoming(rows, current=True, today=today, lead_time_days=7, target_days=30)
    first = incoming.for_warehouses({"1"})
    assert first.quantity(["42"]) == 20 and first.events(["42"]) == [Arrival(7, 20)]
    assert incoming.quantity(["42"]) == 70


def test_unknown_incoming_warehouse_does_not_become_a_false_zero_in_each_cluster():
    today = date.today()
    rows = [
        dict(
            status="planned",
            planned_date=str(today),
            goods_complete=True,
            warehouse_id=warehouse,
            goods=[{"product_key": "42", "quantity": quantity}],
        )
        for warehouse, quantity in [("1", 20), ("99", 50)]
    ]
    native = Incoming(rows, current=True, today=today, lead_time_days=7, target_days=30)
    first = native.for_warehouses({"1"}, {"1", "2"})
    assert first.quantity(["42"]) is None and not first.complete
    assert first.events(["42"]) == [Arrival(7, 20)]


def test_invalid_optional_cluster_metric_does_not_break_the_existing_global_stock_report():
    facts = normalize([dict(stock_row(available=10, ads="1"), ads_cluster="not-a-number")])["101"]
    assert facts["available"] == 10 and facts["ads"] == "1"
    assert facts["destinations"][0]["daily_orders"] is None
