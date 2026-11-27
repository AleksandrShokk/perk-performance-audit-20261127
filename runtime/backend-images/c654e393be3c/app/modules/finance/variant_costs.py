"""Cost versions keyed by neutral variant ID; no Ozon IDs in WB nm_id fields."""

from collections import defaultdict
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.modules.accounts.access import require_permission
from app.modules.accounts.router import find_store
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.catalog.identifiers import product_key, variant_key
from app.modules.finance.marketplace_models import MarketplaceVariantCost
from app.modules.finance.router import owner_store
from app.modules.finance.schemas import VariantCostInput, VariantCostView

router = APIRouter(prefix="/workspaces/{workspace_id}/stores/{store_id}", tags=["Finance"])


def aad(wid, sid, variant_id, currency, effective):
    return f"perk-variant-cost:v1:{wid}:{sid}:{variant_id}:{currency}:{effective}"


def view(vault, row):
    value = vault.open(
        row.ciphertext,
        aad(row.workspace_id, row.store_id, row.variant_id, row.currency, row.effective_from),
    )
    return VariantCostView(
        variant_id=row.variant_id,
        amount=Decimal(value),
        currency=row.currency,
        effective_from=row.effective_from,
        created_at=row.created_at,
    )


def book(db, vault, wid, sid, currency, end):
    rows = db.scalars(
        select(MarketplaceVariantCost)
        .where(
            MarketplaceVariantCost.workspace_id == wid,
            MarketplaceVariantCost.store_id == sid,
            MarketplaceVariantCost.currency == currency,
            MarketplaceVariantCost.effective_from <= end,
        )
        .order_by(MarketplaceVariantCost.effective_from.desc())
        .limit(200001)
    ).all()
    if len(rows) > 200000:
        raise HTTPException(422, "Слишком много версий себестоимости. Уточните период.")
    result = defaultdict(list)
    for row in rows:
        result[str(row.variant_id)].append((row.effective_from, view(vault, row).amount))
    return result


def resolve(prices, variant_id, day):
    return next(
        (amount for effective, amount in prices.get(str(variant_id), []) if effective <= day), None
    )


def sku_variants(catalog, store_id):
    result = {}
    for row in catalog or []:
        vid = variant_key(product_key(store_id, "ozon", row["external_id"]), row["external_id"])
        for sku in set(
            [
                row["marketplace_code"],
                *row.get("sku_aliases", []),
                *(sku for values in row.get("channel_skus", {}).values() for sku in values),
            ]
        ):
            if not sku:
                continue
            # Conflicting native identifiers are unknown; never assign someone else's cost.
            result[sku] = vid if sku not in result or result[sku] == vid else None
    return result


def apply(item, prices, day):
    missing = 0
    for variant in item.variants:
        price = resolve(prices, variant.id, day)
        variant.unit_cost = format(price, "f") if price is not None else None
        missing += price is None
    item.missing_cost_variants = missing
    return item


@router.get("/variant-costs", response_model=list[VariantCostView], operation_id="variantCostsList")
def history(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    variant_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    require_permission(db, identity, workspace_id, "profit.read")
    find_store(db, workspace_id, store_id)
    query = select(MarketplaceVariantCost).where(
        MarketplaceVariantCost.workspace_id == workspace_id,
        MarketplaceVariantCost.store_id == store_id,
    )
    if variant_id:
        query = query.where(MarketplaceVariantCost.variant_id == variant_id)
    rows = db.scalars(
        query.order_by(
            MarketplaceVariantCost.effective_from.desc(), MarketplaceVariantCost.variant_id
        )
        .limit(limit)
        .offset(offset)
    )
    return [view(request.app.state.vault, row) for row in rows]


@router.put("/variant-costs", response_model=VariantCostView, operation_id="variantCostsSave")
def save(
    workspace_id: UUID,
    store_id: UUID,
    data: VariantCostInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    store = owner_store(
        db, identity, workspace_id, store_id, lock=True, permission="costs.write", feature="catalog"
    )
    if store.marketplace != "ozon":
        raise HTTPException(409, "Для WB используется существующая история себестоимости.")
    from app.modules.catalog.ozon_read import snapshot

    catalog, _ = snapshot(db, request.app.state.vault, workspace_id, store)
    valid = {
        variant_key(product_key(store_id, "ozon", row["external_id"]), row["external_id"])
        for row in catalog or []
    }
    if str(data.variant_id) not in valid:
        raise HTTPException(404, "Вариант товара не найден в этом магазине.")
    key = (workspace_id, store_id, data.variant_id, data.currency, data.effective_from)
    ciphertext = request.app.state.vault.seal(format(data.amount, "f"), aad(*key))
    statement = insert(MarketplaceVariantCost).values(
        workspace_id=workspace_id,
        store_id=store_id,
        variant_id=data.variant_id,
        currency=data.currency,
        effective_from=data.effective_from,
        ciphertext=ciphertext,
        created_by=identity.user.id,
        created_at=now(),
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id", "store_id", "variant_id", "currency", "effective_from"],
            set_={"ciphertext": ciphertext},
        )
    )
    row = db.get(MarketplaceVariantCost, key, populate_existing=True)
    result = view(request.app.state.vault, row)
    audit(
        db,
        "cost.variant_saved",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return result
