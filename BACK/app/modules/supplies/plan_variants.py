"""Frozen native sizes/barcodes. No guessed size demand or cross-store matching."""

from fastapi import HTTPException

from app.modules.catalog.service import products
from app.modules.supplies.plan_schemas import PlanVariant


def catalog(db, vault, store):
    page = products(
        db,
        vault,
        store.workspace_id,
        [store],
        currency="RUB",
        query="",
        only_stock=False,
        missing_cost=False,
        can_stock=False,
        can_cost=False,
        limit=None,
        offset=0,
    )
    return {
        (item.nm_id if store.marketplace == "wildberries" else item.id): [
            PlanVariant(
                variant_id=variant.id,
                external_id=variant.external_id,
                size=variant.size,
                barcodes=list(dict.fromkeys(variant.barcodes)),
                barcode=variant.barcodes[0] if len(set(variant.barcodes)) == 1 else "",
            )
            for variant in item.variants
        ]
        for item in page.items
    }


def attach(items, choices):
    changed = 0
    for item in items:
        if item.variants or not choices.get(item.product_key):
            continue
        item.variants = [variant.model_copy(deep=True) for variant in choices[item.product_key]]
        if len(item.variants) == 1:
            item.variants[0].quantity = item.quantity
        changed += 1
    return changed


def apply(item, value):
    if value.variants is not None:
        inputs = {row.variant_id: row for row in value.variants}
        if len(inputs) != len(value.variants) or set(inputs) != {
            row.variant_id for row in item.variants
        }:
            raise HTTPException(422, "Размеры не совпадают с сохранённым планом.")
        for variant in item.variants:
            data = inputs[variant.variant_id]
            if data.barcode and data.barcode not in variant.barcodes:
                raise HTTPException(422, "Штрихкод не принадлежит выбранному размеру.")
            variant.quantity, variant.barcode = data.quantity, data.barcode
    elif len(item.variants) == 1:
        # Backward-compatible product quantity edits also update its single native size.
        item.variants[0].quantity = value.quantity
    if sum(row.quantity for row in item.variants) > value.quantity:
        raise HTTPException(422, "Количество по размерам превышает количество товара.")


def allocation(items):
    allocated = sum(variant.quantity for item in items for variant in item.variants)
    error, used = None, set()
    for item in items:
        label = item.vendor_code or item.marketplace_code or item.nm_id
        count = sum(row.quantity for row in item.variants)
        if count != item.quantity:
            error = error or f"Распределите количество по размерам: {label}."
        for row in item.variants:
            if not row.quantity:
                continue
            if not row.barcode or row.barcode not in row.barcodes:
                error = error or f"Выберите штрихкод: {label}, {row.size or 'без размера'}."
            elif row.barcode in used:
                error = error or f"Штрихкод {row.barcode} используется в нескольких позициях."
            used.add(row.barcode)
    if not any(item.quantity for item in items):
        error = "В плане нет товаров для выгрузки."
    return allocated, error
