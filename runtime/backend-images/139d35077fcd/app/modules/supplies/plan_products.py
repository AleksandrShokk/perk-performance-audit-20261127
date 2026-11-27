"""Explicit selection from the store's own catalogue; server owns all metadata."""

from fastapi import HTTPException

from app.modules.auth.dependencies import now
from app.modules.catalog.service import products
from app.modules.supplies import packaging, plan_variants, plans, service
from app.modules.supplies.plan_schemas import PlanLine


def candidates(db, vault, store, saved):
    catalogue = products(
        db,
        vault,
        store.workspace_id,
        [store],
        currency="RUB",
        query="",
        only_stock=False,
        missing_cost=False,
        can_stock=True,
        can_cost=False,
        limit=None,
        offset=0,
    )
    report = service.replenishment(
        db,
        vault,
        store.workspace_id,
        [store],
        limit=None,
        include_fbs=saved.include_fbs,
        target_days=saved.target_days,
        lead_time_days=saved.lead_time_days,
        urgent_only=False,
        destination_id=saved.destination_id or None,
    )
    recommendations = {packaging.product_key(item): item for item in report.items}
    multiples = packaging.multiples(db, store.workspace_id, [store])
    result = []
    for product in catalogue.items:
        key = product.nm_id if store.marketplace == "wildberries" else product.id
        recommended = recommendations.get(key)
        multiple = multiples.get((str(store.id), key), 1)
        values = (
            recommended.model_dump()
            if recommended
            else dict(
                id=key,
                marketplace=store.marketplace,
                marketplace_code=product.marketplace_code,
                demand_basis="ozon_sales" if store.marketplace == "ozon" else "wb_orders",
                store_id=store.id,
                store_name=store.name,
                nm_id=product.nm_id,
                vendor_code=product.vendor_code,
                title=product.title,
                photo=next(iter(product.photos), None),
                colors=product.colors,
                barcodes=list(dict.fromkeys(b for v in product.variants for b in v.barcodes)),
                stock=product.stock or 0,
                daily_orders="0",
                days_of_stock="0",
                quantity=0,
                box_multiple=multiple,
                urgent=False,
            )
        )
        result.append(
            PlanLine(
                **{**values, "quantity": 0},
                product_key=key,
                recommended_quantity=recommended.quantity if recommended else 0,
            )
        )
    plan_variants.attach(result, plan_variants.catalog(db, vault, store))
    return result


def persist(db, vault, row, saved, user_id):
    row.revision += 1
    row.updated_by, row.updated_at = user_id, now()
    row.ciphertext = vault.seal(saved.model_dump_json(), plans.aad(row))
    db.flush()


def add(db, vault, row, store, user_id, data):
    if data.revision != row.revision:
        raise HTTPException(409, "План уже изменён. Откройте его заново.")
    saved = plans.snapshot(vault, row)
    choices = {item.product_key: item for item in candidates(db, vault, store, saved)}
    keys = set(data.product_keys)
    if keys - choices.keys():
        raise HTTPException(422, "Выбранные товары не найдены в этом кабинете.")
    existing = {item.product_key for item in saved.items}
    additions = [choices[key] for key in dict.fromkeys(data.product_keys) if key not in existing]
    if len(saved.items) + len(additions) > 5000:
        raise HTTPException(422, "В плане может быть не больше 5000 товаров.")
    saved.items.extend(additions)
    persist(db, vault, row, saved, user_id)
