"""Published reporting providers; verified connections alone are not imported data."""

from fastapi import HTTPException
from sqlalchemy import select

from app.modules.accounts.models import Store

# Legacy WB reports keep their original guards; neutral adapters opt into individual features.
REPORTING_MARKETPLACES = frozenset({"wildberries"})
FEATURES = {
    "wildberries": (
        "catalog",
        "inventory",
        "finance",
        "finance_details",
        "analytics",
        "supplies",
        "supply_history",
    ),
    "ozon": (
        "catalog",
        "inventory",
        "analytics",
        "finance",
        "finance_details",
        "supplies",
        "supply_history",
    ),
}


def supports(store, feature):
    return (
        store.marketplace in REPORTING_MARKETPLACES
        if feature == "reports"
        else feature in FEATURES.get(store.marketplace, ())
    )


def require_reporting_store(store, feature="reports"):
    if not supports(store, feature):
        raise HTTPException(
            409,
            {
                "code": "marketplace_not_ready",
                "message": "Этот раздел Ozon будет добавлен следующим этапом.",
            },
        )
    return store


def reporting_stores(
    db,
    workspace_id,
    store_id=None,
    *,
    by_created=False,
    limit=None,
    missing_ok=False,
    feature="reports",
):
    # RLS and workspace filtering apply before provider selection.
    query = select(Store).where(Store.workspace_id == workspace_id, Store.is_active.is_(True))
    if store_id:
        query = query.where(Store.id == store_id)
    query = query.order_by(Store.created_at if by_created else Store.id)
    if limit is not None:
        query = query.limit(limit)
    rows = db.scalars(query).all()
    if store_id:
        if not rows:
            if missing_ok:
                return []
            raise HTTPException(404, "Магазин не найден.")
        require_reporting_store(rows[0], feature)
    if not store_id and feature == "reports" and any(store.marketplace == "ozon" for store in rows):
        raise HTTPException(
            409,
            {
                "code": "marketplace_not_ready",
                "message": "Общий отчёт WB и Ozon будет доступен после подключения данных Ozon.",
            },
        )
    return [store for store in rows if supports(store, feature)]
