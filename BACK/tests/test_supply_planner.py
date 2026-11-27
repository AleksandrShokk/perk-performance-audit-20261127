import csv
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.supplies.export import requirements_csv
from app.modules.supplies.packaging import PackagingInput, apply
from app.modules.supplies.schemas import ReplenishmentItem, ReplenishmentOverview
from app.modules.supplies.service import from_demand


@pytest.mark.parametrize(
    "target,lead,expected", [(30, 7, 85), (14, 0, 0), (60, 0, 200), (30, 90, 150), (1, 0, 0)]
)
def test_custom_horizon_uses_stock_at_arrival_without_creating_a_lost_order_backlog(
    target, lead, expected
):
    result = from_demand(100, Decimal(5), target_days=target, lead_time_days=lead)
    assert result["quantity"] == expected
    assert result["daily_orders"] == "5"
    assert result["days_of_stock"] == "20.00"


def item(store=None, **changes):
    return ReplenishmentItem(
        store_id=store or uuid4(),
        store_name="Store",
        nm_id="42",
        vendor_code="00042",
        title="Product",
        photo=None,
        colors=[],
        barcodes=["000042"],
        stock=10,
        daily_orders="1.25",
        days_of_stock="8",
        quantity=11,
        urgent=False,
        **changes,
    )


def test_packaging_rounds_up_per_cabinet_and_never_changes_native_identity():
    first = item()
    other = item()
    rounded = apply([first, other], {(str(first.store_id), "42"): 5})
    assert [row.quantity for row in rounded] == [15, 11]
    assert [row.required_quantity for row in rounded] == [11, 11]
    assert rounded[0].nm_id == first.nm_id and rounded[0].box_multiple == 5
    assert first.quantity == 11


def test_native_ozon_product_key_cannot_collide_with_a_wb_article():
    first = item(id=str(uuid4()), marketplace="ozon", marketplace_code="42")
    rounded = apply([first], {(str(first.store_id), "42"): 5})
    assert rounded[0].quantity == 11
    assert apply([first], {(str(first.store_id), first.id): 5})[0].quantity == 15


@pytest.mark.parametrize("value", [0, -1, 10001, 1.5, "5", True])
def test_invalid_packaging_is_rejected(value):
    with pytest.raises(ValidationError):
        PackagingInput(box_multiple=value)


def test_csv_has_all_rows_exact_quantities_native_ids_and_safe_seller_text():
    first = item()
    first.title = '=HYPERLINK("unsafe")'
    first.store_name = " @SUM(1;2)"
    data = ReplenishmentOverview(
        target_days=45,
        lead_time_days=3,
        recommended_units=30,
        product_count=2,
        urgent_count=0,
        unknown_count=1,
        no_orders_count=0,
        partial=True,
        loading=False,
        stale=False,
        updated_at=datetime(2026, 11, 6, tzinfo=UTC),
        items=apply([first, item()], {(str(first.store_id), "42"): 5}),
        count=2,
        limit=2,
        offset=0,
    )
    content = requirements_csv(data).decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(content), delimiter=";"))
    assert len(rows) == 2
    assert rows[0]["К поставке, шт."] == "15" and rows[0]["Коробов"] == "3"
    assert rows[0]["Потребность, шт."] == "11"
    assert rows[0]["Товар"].startswith("'=HYPERLINK")
    assert rows[0]["Кабинет"].startswith("' @SUM")
    assert rows[0]["Состояние данных"] == "Частичные"
    assert rows[0]["Запас после поступления, дней"] == "45"
    assert rows[0]["Артикул площадки"] == "'42"
    assert rows[0]["Артикул продавца"] == "'00042"
    assert rows[0]["Штрихкоды"] == "'000042"


def test_zero_and_exact_box_quantities_are_not_increased():
    row = item()
    row.quantity = 0
    key = (str(row.store_id), "42")
    assert apply([row], {key: 5})[0].quantity == 0
    row.quantity = 10
    assert apply([row], {key: 5})[0].quantity == 10
