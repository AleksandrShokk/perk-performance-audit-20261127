"""The same bounded preview/apply workflow as WB, with native Ozon SKU -> variant IDs."""

import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert

from app.modules.catalog.ozon_read import snapshot
from app.modules.finance.marketplace_models import MarketplaceVariantCost
from app.modules.finance.models import CostImport
from app.modules.finance.schemas import (
    ImportPreview,
    ImportResult,
    RowError,
    VariantCostInput,
    VariantPreviewItem,
)
from app.modules.finance.service import import_aad
from app.modules.finance.variant_costs import aad, sku_variants, view
from app.modules.finance.xlsx import HEADERS, build_template

OZON_HEADERS = ("SKU Ozon", *HEADERS[1:])


def catalog_index(db, vault, store):
    catalog, _ = snapshot(db, vault, store.workspace_id, store)
    if catalog is None:
        raise HTTPException(409, "Дождитесь загрузки каталога Ozon.")
    mapping = sku_variants(catalog, store.id)
    products = {}
    for row in catalog:
        for sku in [
            row["marketplace_code"],
            *row.get("sku_aliases", []),
            *(sku for values in row.get("channel_skus", {}).values() for sku in values),
        ]:
            if mapping.get(sku):
                products[sku] = row
    return catalog, mapping, products


def template(db, vault, store, currency, today):
    catalog, mapping, _ = catalog_index(db, vault, store)
    if len(catalog) > 5000:
        raise HTTPException(422, "В каталоге больше 5000 вариантов. Разделите файл на части.")
    rows = [
        (row["marketplace_code"], "", "", today.isoformat(), currency)
        for row in catalog
        if mapping.get(row["marketplace_code"])
    ]
    return build_template(OZON_HEADERS, rows)


def check(db, vault, store, inputs):
    _, mapping, products = catalog_index(db, vault, store)
    errors, actions = [], []
    for number, sku, barcode, value in inputs:
        product = products.get(sku)
        if mapping.get(sku) != str(value.variant_id) or not product:
            errors.append(
                RowError(
                    row=number,
                    field="marketplace_code",
                    code="unknown_product",
                    message="SKU не найден в каталоге этого магазина.",
                )
            )
            continue
        if barcode and barcode not in product["barcodes"]:
            errors.append(
                RowError(
                    row=number,
                    field="barcode",
                    code="unknown_barcode",
                    message="Баркод не принадлежит этому SKU.",
                )
            )
            continue
        key = (store.workspace_id, store.id, value.variant_id, value.currency, value.effective_from)
        saved = db.get(MarketplaceVariantCost, key)
        if saved and view(vault, saved).amount != value.amount:
            errors.append(
                RowError(
                    row=number,
                    field="effective_from",
                    code="price_conflict",
                    message="На эту дату уже сохранена другая цена. Проверьте дату.",
                )
            )
            continue
        actions.append(
            VariantPreviewItem(
                **value.model_dump(),
                row=number,
                marketplace_code=sku,
                product_title=product["title"],
                action="unchanged" if saved else "insert",
            )
        )
    return errors, actions


def preview(db, vault, store, user_id, raw_rows, currency, now):
    _, mapping, _ = catalog_index(db, vault, store)
    inputs, errors, seen = [], [], set()
    filled = [(number, cells) for number, cells in raw_rows if cells[2].strip()]
    for number, cells in filled:
        sku, barcode = cells[0].strip(), cells[1].strip()
        if not mapping.get(sku):
            errors.append(
                RowError(
                    row=number,
                    field="marketplace_code",
                    code="unknown_product",
                    message="SKU не найден в каталоге этого магазина.",
                )
            )
            continue
        try:
            value = VariantCostInput(
                variant_id=mapping[sku],
                amount=cells[2].replace("\u00a0", "").replace(" ", "").replace(",", "."),
                currency=cells[4].upper() or currency,
                effective_from=cells[3].split("T")[0],
            )
        except ValidationError:
            errors.append(
                RowError(
                    row=number,
                    field="amount",
                    code="invalid_value",
                    message="Проверьте цену, валюту и дату.",
                )
            )
            continue
        key = (value.variant_id, value.currency, value.effective_from)
        if key in seen:
            errors.append(
                RowError(
                    row=number,
                    field="marketplace_code",
                    code="duplicate_price",
                    message="Повтор варианта, валюты и даты в файле.",
                )
            )
            continue
        seen.add(key)
        inputs.append((number, sku, barcode, value))
    validation, actions = check(db, vault, store, inputs)
    errors.extend(validation)
    if not filled:
        errors.append(
            RowError(
                row=2, field="amount", code="empty_file", message="Заполните хотя бы одну цену."
            )
        )
    saved = None
    if not errors:
        saved = CostImport(
            workspace_id=store.workspace_id,
            store_id=store.id,
            id=uuid4(),
            created_by=user_id,
            expires_at=now + timedelta(minutes=30),
        )
        payload = {
            "kind": "ozon_variants_v1",
            "rows": [
                {"row": n, "sku": sku, "barcode": barcode, "value": v.model_dump(mode="json")}
                for n, sku, barcode, v in inputs
            ],
        }
        saved.ciphertext = vault.seal(
            json.dumps(payload), import_aad(store.workspace_id, store.id, saved.id)
        )
        db.add(saved)
    return ImportPreview(
        preview_id=saved.id if saved else None,
        expires_at=saved.expires_at if saved else None,
        rows_count=len(filled),
        valid_count=len(actions),
        error_count=len(errors),
        errors=errors[:100],
        items=actions[:100],
        can_apply=not errors,
    )


def apply(db, vault, store, user_id, preview, now):
    context = import_aad(store.workspace_id, store.id, preview.id)
    payload = json.loads(vault.open(preview.ciphertext, context))
    if payload.get("kind") != "ozon_variants_v1":
        raise HTTPException(409, "Загрузите файл для этого маркетплейса заново.")
    if "result" in payload:
        return ImportResult.model_validate(payload["result"])
    if preview.expires_at <= now:
        raise HTTPException(410, "Предпросмотр истёк. Загрузите файл ещё раз.")
    inputs = [
        (row["row"], row["sku"], row["barcode"], VariantCostInput.model_validate(row["value"]))
        for row in payload["rows"]
    ]
    errors, actions = check(db, vault, store, inputs)
    if errors:
        raise HTTPException(409, "Каталог или цены изменились. Загрузите файл для новой проверки.")
    inserted = 0
    for _, _, _, value in inputs:
        key = (store.workspace_id, store.id, value.variant_id, value.currency, value.effective_from)
        statement = insert(MarketplaceVariantCost).values(
            workspace_id=store.workspace_id,
            store_id=store.id,
            variant_id=value.variant_id,
            currency=value.currency,
            effective_from=value.effective_from,
            ciphertext=vault.seal(format(value.amount, "f"), aad(*key)),
            created_by=user_id,
            created_at=now,
        )
        new = db.scalar(
            statement.on_conflict_do_nothing().returning(MarketplaceVariantCost.variant_id)
        )
        if new:
            inserted += 1
        else:
            saved = db.get(MarketplaceVariantCost, key, populate_existing=True)
            if view(vault, saved).amount != Decimal(value.amount):
                raise HTTPException(409, "Цена изменилась. Загрузите файл для новой проверки.")
    result = ImportResult(
        preview_id=preview.id, inserted=inserted, unchanged=len(actions) - inserted
    )
    preview.ciphertext = vault.seal(
        json.dumps({"kind": "ozon_variants_v1", "result": result.model_dump(mode="json")}), context
    )
    return result
