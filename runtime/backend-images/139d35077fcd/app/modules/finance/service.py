import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, tuple_

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.finance.models import CostImport, ExternalExpense, ProductCost
from app.modules.finance.schemas import (
    CostInput,
    ExpenseView,
    ImportPreview,
    ImportResult,
    PreviewItem,
    RowError,
    UnitCostResult,
)
from app.modules.sync.models import WBRecord
from app.modules.sync.service import context


def price_key(value):
    return value.nm_id, value.barcode, value.currency, value.effective_from


def price_aad(workspace_id, store_id, value):
    return "perk-cost:v1:" + json.dumps(
        [
            str(workspace_id),
            str(store_id),
            value.nm_id,
            value.barcode,
            value.currency,
            value.effective_from.isoformat(),
        ],
        separators=(",", ":"),
    )


def import_aad(workspace_id, store_id, preview_id):
    return f"perk-cost-import:v1:{workspace_id}:{store_id}:{preview_id}"


def expense_aad(workspace_id, store_id, expense_id):
    return f"perk-expense:v1:{workspace_id}:{store_id}:{expense_id}"


def unit_amount(vault, row):
    return Decimal(vault.open(row.ciphertext, price_aad(row.workspace_id, row.store_id, row)))


def existing_prices(db, workspace_id, store_id, inputs):
    keys = list({price_key(value) for value in inputs})
    result = {}
    for offset in range(0, len(keys), 500):
        rows = db.scalars(
            select(ProductCost).where(
                *scope(ProductCost, workspace_id, store_id),
                tuple_(
                    ProductCost.nm_id,
                    ProductCost.barcode,
                    ProductCost.currency,
                    ProductCost.effective_from,
                ).in_(keys[offset : offset + 500]),
            )
        ).all()
        result.update({price_key(row): row for row in rows})
    return result


def catalog_items(db, vault, workspace_id, store_id, inputs):
    identifiers = sorted({value.nm_id for value in inputs})
    result = {}
    for offset in range(0, len(identifiers), 500):
        rows = db.scalars(
            select(WBRecord).where(
                *scope(WBRecord, workspace_id, store_id),
                WBRecord.source == Source.CATALOG,
                WBRecord.record_key.in_(identifiers[offset : offset + 500]),
            )
        ).all()
        for row in rows:
            result[row.record_key] = json.loads(
                vault.open(
                    row.ciphertext,
                    context(workspace_id, store_id, Source.CATALOG, row.record_key),
                )
            )
    return result


def validate_costs(db, vault, workspace_id, store_id, inputs):
    values = [value for _, value in inputs]
    catalog = catalog_items(db, vault, workspace_id, store_id, values)
    existing = existing_prices(db, workspace_id, store_id, values)
    errors, actions = [], []
    for row_number, value in inputs:
        product = catalog.get(value.nm_id)
        if product is None:
            errors.append(
                RowError(
                    row=row_number,
                    field="nm_id",
                    code="unknown_product",
                    message="Артикул не найден в каталоге этого магазина.",
                )
            )
            continue
        barcodes = {code for size in product.get("sizes", []) for code in size["barcodes"]}
        if value.barcode and value.barcode not in barcodes:
            errors.append(
                RowError(
                    row=row_number,
                    field="barcode",
                    code="unknown_barcode",
                    message="Баркод не принадлежит этому артикулу.",
                )
            )
            continue
        saved = existing.get(price_key(value))
        if saved and unit_amount(vault, saved) != value.amount:
            errors.append(
                RowError(
                    row=row_number,
                    field="effective_from",
                    code="price_conflict",
                    message="На эту дату уже сохранена другая цена. Проверьте дату.",
                )
            )
            continue
        actions.append(
            PreviewItem(
                **value.model_dump(),
                row=row_number,
                product_title=product["title"],
                action="unchanged" if saved else "insert",
            )
        )
    return errors, actions, existing


def create_preview(db, vault, workspace_id, store_id, user_id, raw_rows, currency, now):
    inputs, errors, seen = [], [], set()
    for number, cells in raw_rows:
        try:
            value = CostInput(
                nm_id=cells[0],
                barcode=cells[1],
                amount=cells[2].replace("\u00a0", "").replace(" ", "").replace(",", "."),
                effective_from=cells[3].split("T")[0],
                currency=cells[4].upper() or currency,
            )
        except ValidationError as exc:
            for error in exc.errors():
                errors.append(
                    RowError(
                        row=number,
                        field=str(error["loc"][0]),
                        code="invalid_value",
                        message="Проверьте значение ячейки.",
                    )
                )
            continue
        key = price_key(value)
        if key in seen:
            errors.append(
                RowError(
                    row=number,
                    field="nm_id",
                    code="duplicate_price",
                    message="Повтор артикула, баркода, валюты и даты в файле.",
                )
            )
            continue
        seen.add(key)
        inputs.append((number, value))
    validation, actions, _ = validate_costs(db, vault, workspace_id, store_id, inputs)
    errors.extend(validation)
    if not raw_rows:
        errors.append(
            RowError(
                row=2,
                field="amount",
                code="empty_file",
                message="Заполните хотя бы одну строку себестоимости.",
            )
        )
    preview = None
    if not errors:
        preview = CostImport(
            workspace_id=workspace_id,
            store_id=store_id,
            id=uuid4(),
            created_by=user_id,
            expires_at=now + timedelta(minutes=30),
        )
        payload = {
            "rows": [
                {"row": number, "value": value.model_dump(mode="json")} for number, value in inputs
            ]
        }
        preview.ciphertext = vault.seal(
            json.dumps(payload), import_aad(workspace_id, store_id, preview.id)
        )
        db.add(preview)
    return ImportPreview(
        preview_id=preview.id if preview else None,
        expires_at=preview.expires_at if preview else None,
        rows_count=len(raw_rows),
        valid_count=len(actions),
        error_count=len(errors),
        errors=errors[:100],
        items=actions[:100],
        can_apply=not errors,
    )


def apply_preview(db, vault, workspace_id, store_id, user_id, preview, now):
    payload = json.loads(
        vault.open(preview.ciphertext, import_aad(workspace_id, store_id, preview.id))
    )
    if "result" in payload:
        return ImportResult.model_validate(payload["result"])
    if preview.expires_at <= now:
        raise HTTPException(410, "Предпросмотр истёк. Загрузите файл ещё раз.")
    inputs = [(row["row"], CostInput.model_validate(row["value"])) for row in payload["rows"]]
    errors, actions, existing = validate_costs(db, vault, workspace_id, store_id, inputs)
    if errors:
        raise HTTPException(409, "Каталог или цены изменились. Загрузите файл для новой проверки.")
    inserted = 0
    for _, value in inputs:
        if price_key(value) in existing:
            continue
        db.add(
            ProductCost(
                workspace_id=workspace_id,
                store_id=store_id,
                created_by=user_id,
                **value.model_dump(exclude={"amount"}),
                ciphertext=vault.seal(str(value.amount), price_aad(workspace_id, store_id, value)),
            )
        )
        inserted += 1
    result = ImportResult(
        preview_id=preview.id, inserted=inserted, unchanged=len(actions) - inserted
    )
    payload = {"result": result.model_dump(mode="json")}
    preview.ciphertext = vault.seal(
        json.dumps(payload), import_aad(workspace_id, store_id, preview.id)
    )
    return result


def resolve_cost(db, vault, workspace_id, store_id, nm_id, barcode, currency, at, quantity=1):
    selected = None
    for match in [barcode, ""] if barcode else [""]:
        selected = db.scalar(
            select(ProductCost)
            .where(
                *scope(ProductCost, workspace_id, store_id),
                ProductCost.nm_id == nm_id,
                ProductCost.barcode == match,
                ProductCost.currency == currency,
                ProductCost.effective_from <= at,
            )
            .order_by(ProductCost.effective_from.desc())
            .limit(1)
        )
        if selected:
            break
    amount = unit_amount(vault, selected) if selected else None
    # Mirrors report.price_for: without a barcode a size override makes the general price unsafe.
    ambiguous = not barcode and bool(
        db.scalar(
            select(ProductCost.nm_id)
            .where(
                *scope(ProductCost, workspace_id, store_id),
                ProductCost.nm_id == nm_id,
                ProductCost.barcode != "",
                ProductCost.currency == currency,
                ProductCost.effective_from <= at,
            )
            .limit(1)
        )
    )
    return UnitCostResult(
        size_prices_exist=ambiguous,
        nm_id=nm_id,
        barcode=barcode,
        currency=currency,
        at=at,
        quantity=quantity,
        unit_cost=format(amount, "f") if amount is not None else None,
        total_cost=format(amount * quantity, "f") if amount is not None else None,
        effective_from=selected.effective_from if selected else None,
        matched_by=("barcode" if selected.barcode else "article") if selected else None,
        available=amount is not None,
    )


def expense_view(vault, row):
    value = json.loads(
        vault.open(row.ciphertext, expense_aad(row.workspace_id, row.store_id, row.id))
    )
    return ExpenseView(
        id=row.id,
        expense_date=row.expense_date,
        currency=row.currency,
        amount=value["amount"],
        comment=value["comment"],
        category=value.get("category", "other"),
        custom_category=value.get("custom_category", ""),
        created_at=row.created_at,
    )


def expense_totals(db, vault, workspace_id, store_id, start, end):
    totals = defaultdict(lambda: {"amount": Decimal(0), "count": 0})
    rows = db.scalars(
        select(ExternalExpense)
        .where(
            *scope(ExternalExpense, workspace_id, store_id),
            ExternalExpense.deleted_at.is_(None),
            ExternalExpense.expense_date.between(start, end),
        )
        .limit(10001)
    ).all()
    if len(rows) > 10000:
        raise HTTPException(422, "Слишком много расходов. Уточните период отчёта.")
    for row in rows:
        value = expense_view(vault, row)
        totals[row.currency]["amount"] += Decimal(value.amount)
        totals[row.currency]["count"] += 1
    return [
        {
            "currency": key,
            "amount": format(value["amount"], "f"),
            "count": value["count"],
        }
        for key, value in sorted(totals.items())
    ]


def identify_products(db, vault, workspace_id, store_id, products):
    """Resolve only returned products in this store; keep identifiers out of money caches."""
    catalog = catalog_items(db, vault, workspace_id, store_id, products)
    for product in products:
        item = catalog.get(product.nm_id, {})
        product.vendor_code = (item.get("vendor_code") or "").strip() or None
        barcodes = {
            code for size in item.get("sizes", []) for code in size.get("barcodes", []) if code
        }
        product.barcodes = sorted(set(product.barcodes) | barcodes)


def barcode_cost_inputs(db, vault, workspace_id, store_id, data):
    """Apply a size's price to its verified aliases, never to a different size."""
    if not data.barcode:
        return [data]
    card = catalog_items(db, vault, workspace_id, store_id, [data]).get(data.nm_id, {})
    sizes = [size for size in card.get("sizes", []) if data.barcode in size.get("barcodes", [])]
    if len(sizes) != 1:
        return [data]
    return [
        data.model_copy(update={"barcode": code}) for code in dict.fromkeys(sizes[0]["barcodes"])
    ]
