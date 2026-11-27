"""Atomic plan import: validate file rows against this cabinet before changing the plan."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app.modules.supplies import plan_products, plans
from app.modules.supplies.template_workbook import InvalidTemplate

KEY_HEADERS = {"артикул", "артикул продавца", "offer_id", "баркод", "штрихкод", "barcode"}
QUANTITY_HEADERS = {"количество", "количество, шт.", "quantity", "кол-во"}


def read_rows(book):
    for sheet in book.inspect():
        for header in sheet.headers:
            keys = [c for c in header.columns if c.label.casefold() in KEY_HEADERS]
            quantities = [c for c in header.columns if c.label.casefold() in QUANTITY_HEADERS]
            if len(keys) != 1 or len(quantities) != 1:
                continue
            key, quantity = keys[0], quantities[0]
            barcode = key.label.casefold() in {"баркод", "штрихкод", "barcode"}
            _, _, _, grid = book.grid(sheet.name)
            rows = []
            seen = set()
            for number, cells in sorted(grid.items()):
                if number <= header.row:
                    continue
                identifier = book.value(cells.get(key.key))
                raw = book.value(cells.get(quantity.key))
                if not identifier and not raw:
                    continue
                if not identifier:
                    raise InvalidTemplate(f"Строка {number}: не указан товар.")
                try:
                    value = Decimal(raw)
                    if (
                        not value.is_finite()
                        or not 0 <= value <= 2147483647
                        or value != value.to_integral_value()
                    ):
                        raise InvalidOperation
                except InvalidOperation:
                    raise InvalidTemplate(
                        f"Строка {number}: укажите целое количество от 0."
                    ) from None
                if identifier in seen:
                    raise InvalidTemplate(f"Строка {number}: товар {identifier} повторяется.")
                seen.add(identifier)
                if value:
                    rows.append((number, identifier, int(value)))
                if len(seen) > 5000:
                    raise InvalidTemplate("В файле может быть не больше 5000 позиций.")
            if not rows:
                raise InvalidTemplate("В файле нет товаров с количеством больше нуля.")
            return barcode, rows
    raise InvalidTemplate("Нужны столбцы «Артикул продавца» или «Баркод» и «Количество».")


def apply(db, vault, row, store, user_id, revision, book):
    if row.revision != revision:
        raise HTTPException(409, "План уже изменён. Откройте его заново.")
    barcode, rows = read_rows(book)
    saved = plans.snapshot(vault, row)
    catalogue = plan_products.candidates(db, vault, store, saved)
    index = defaultdict(list)
    for item in catalogue:
        if barcode:
            for variant in item.variants:
                for code in variant.barcodes:
                    index[code].append((item, variant.variant_id))
        elif item.vendor_code:
            index[item.vendor_code].append((item, None))
    unknown = [(n, key) for n, key, _ in rows if not index[key]]
    if unknown:
        examples = "; ".join(f"строка {n}: {key}" for n, key in unknown[:5])
        raise InvalidTemplate(f"В кабинете не найдены товары из файла: {len(unknown)}. {examples}.")
    imported = {}
    for number, key, quantity in rows:
        if len(index[key]) != 1:
            raise InvalidTemplate(
                f"Строка {number}: {key} соответствует нескольким товарам. "
                "Используйте баркод размера."
            )
        source, variant_id = index[key][0]
        if not barcode and len(source.variants) != 1:
            raise InvalidTemplate(
                f"Строка {number}: у товара несколько размеров. Используйте баркод размера."
            )
        item = imported.setdefault(source.product_key, source.model_copy(deep=True))
        item.quantity += quantity
        if item.quantity > 2147483647:
            raise InvalidTemplate(f"Строка {number}: слишком большое количество.")
        variant = next(
            (v for v in item.variants if v.variant_id == variant_id),
            item.variants[0] if len(item.variants) == 1 else None,
        )
        if variant is None:
            raise InvalidTemplate(f"Строка {number}: размер товара не найден.")
        variant.quantity += quantity
        if barcode:
            variant.barcode = key
    for item in imported.values():
        if item.quantity % item.box_multiple:
            raise InvalidTemplate(
                f"{item.vendor_code}: количество должно быть кратно {item.box_multiple}."
            )
    # Replace quantities only for explicitly imported products; keep the rest untouched.
    existing = {item.product_key: item for item in saved.items}
    existing.update(imported)
    if len(existing) > 5000:
        raise InvalidTemplate("В плане может быть не больше 5000 товаров.")
    saved.items = list(existing.values())
    plan_products.persist(db, vault, row, saved, user_id)
