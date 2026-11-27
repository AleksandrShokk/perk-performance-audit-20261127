"""Server-owned snapshots: editable quantities without trusting client product metadata."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.modules.auth.dependencies import now
from app.modules.supplies import plan_variants, service
from app.modules.supplies.models import SupplyPlan
from app.modules.supplies.plan_schemas import PlanSnapshot, PlanSummary, PlanView


def aad(row):
    return f"supply-plan:{row.workspace_id}:{row.store_id}:{row.id}"


def snapshot(vault, row):
    return PlanSnapshot.model_validate_json(vault.open(row.ciphertext, aad(row)))


def summary(row, data, store):
    allocated, error = plan_variants.allocation(data.items)
    return PlanSummary(
        id=row.id,
        store_id=row.store_id,
        store_name=store.name,
        marketplace=store.marketplace,
        title=data.title,
        destination=data.destination,
        destination_id=data.destination_id,
        status=data.status,
        revision=row.revision,
        quantity=sum(item.quantity for item in data.items),
        product_count=sum(item.quantity > 0 for item in data.items),
        allocated_quantity=allocated,
        allocation_complete=error is None,
        allocation_error=error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def view(vault, row, store):
    data = snapshot(vault, row)
    return PlanView(
        **summary(row, data, store).model_dump(),
        **data.model_dump(exclude={"title", "destination", "destination_id", "status"}),
    )


def create(db, vault, store, user_id, data):
    destination = data.destination
    if data.destination_id:
        report = service.replenishment(
            db,
            vault,
            store.workspace_id,
            [store],
            limit=1,
            include_fbs=data.include_fbs,
            target_days=data.target_days,
            lead_time_days=data.lead_time_days,
            destination_id=data.destination_id,
        )
        destination = report.destination_name
    timestamp = now()
    row = SupplyPlan(
        workspace_id=store.workspace_id,
        store_id=store.id,
        id=uuid4(),
        revision=1,
        created_by=user_id,
        updated_by=user_id,
        created_at=timestamp,
        updated_at=timestamp,
    )
    saved = PlanSnapshot(
        include_fbs=data.include_fbs,
        title=data.title,
        destination=destination,
        destination_id=data.destination_id,
        status="draft",
        target_days=data.target_days,
        lead_time_days=data.lead_time_days,
        source_updated_at=None,
        source_partial=False,
        items=[],
    )
    row.ciphertext = vault.seal(saved.model_dump_json(), aad(row))
    db.add(row)
    db.flush()
    return row


def find(db, workspace_id, plan_id, *, lock=False):
    query = select(SupplyPlan).where(
        SupplyPlan.workspace_id == workspace_id, SupplyPlan.id == plan_id
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "План не найден.")
    return row


def load_variants(db, vault, row, store, user_id, revision):
    if row.revision != revision:
        raise HTTPException(409, "План уже изменён. Закройте его и откройте заново.")
    data = snapshot(vault, row)
    if not plan_variants.attach(data.items, plan_variants.catalog(db, vault, store)):
        raise HTTPException(409, "Новые размеры этих товаров пока не найдены в каталоге.")
    row.revision += 1
    row.updated_by, row.updated_at = user_id, now()
    row.ciphertext = vault.seal(data.model_dump_json(), aad(row))
    db.flush()


def update(db, vault, row, user_id, data):
    if row.revision != data.revision:
        raise HTTPException(409, "План уже изменён. Закройте его и откройте заново.")
    saved = snapshot(vault, row)
    if saved.destination_id and data.destination != saved.destination:
        raise HTTPException(409, "Для смены направления создайте новый план.")
    quantities = {item.product_key: item for item in data.items}
    if not set(quantities).issubset({item.product_key for item in saved.items}):
        raise HTTPException(422, "Состав товаров изменён. Откройте план заново.")
    saved.items = [item for item in saved.items if item.product_key in quantities]
    for item in saved.items:
        value = quantities[item.product_key]
        quantity = value.quantity
        plan_variants.apply(item, value)
        if quantity % item.box_multiple:
            raise HTTPException(
                422,
                f"Количество должно быть кратно {item.box_multiple}: "
                f"{item.vendor_code or item.marketplace_code or item.nm_id}.",
            )
        item.quantity = quantity
    if data.status == "ready" and not any(item.quantity for item in saved.items):
        raise HTTPException(422, "Добавьте количество хотя бы для одного товара.")
    saved.title, saved.destination, saved.status = (
        data.title,
        data.destination,
        data.status,
    )
    row.revision += 1
    row.updated_by, row.updated_at = user_id, now()
    row.ciphertext = vault.seal(saved.model_dump_json(), aad(row))
    db.flush()
