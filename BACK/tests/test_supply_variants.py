from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from test_supply_planner import item

from app.modules.supplies.export import plan_items_csv
from app.modules.supplies.plan_schemas import PlanLine, PlanQuantity, PlanVariant, PlanVariantInput
from app.modules.supplies.plan_variants import allocation, apply, attach


def variant(key="v1", **changes):
    return PlanVariant(
        variant_id=key, external_id=key, size="M", barcodes=["0001"], barcode="0001", **changes
    )


def line():
    return PlanLine(**item().model_dump(), product_key="42", recommended_quantity=11)


def test_one_size_receives_quantity_but_multiple_sizes_are_not_guessed():
    first, second = line(), line()
    second.product_key = "43"
    choices = {"42": [variant()], "43": [variant(), variant("v2")]}
    assert attach([first, second], choices) == 2
    assert first.variants[0].quantity == 11
    assert [v.quantity for v in second.variants] == [0, 0]
    assert choices["42"][0].quantity == 0
    assert attach([first, second], choices) == 0


def test_old_quantity_requests_adjust_a_single_size_without_changing_its_barcode():
    row = line()
    row.variants = [variant(quantity=11)]
    apply(row, PlanQuantity(product_key="42", quantity=20))
    assert row.variants[0].quantity == 20 and row.variants[0].barcode == "0001"


@pytest.mark.parametrize("value", [-1, 1.2, True, "5", 2147483648])
def test_variant_quantities_are_strict_bounded_integers(value):
    with pytest.raises(ValidationError):
        PlanVariantInput(variant_id="v", quantity=value)


def test_unallocated_or_duplicate_barcodes_block_a_detailed_export():
    row = line()
    row.variants = [variant(quantity=5)]
    assert allocation([row])[1]
    row.variants.append(variant("v2", quantity=6))
    assert "нескольких" in allocation([row])[1]
    row.variants[1].barcodes = ["0002"]
    row.variants[1].barcode = "0002"
    assert allocation([row]) == (11, None)
    row.variants[1].barcode = ""
    with pytest.raises(HTTPException) as error:
        plan_items_csv(SimpleNamespace(items=[row]))
    assert error.value.status_code == 409
