"""Read existing marketplace read models. No provider calls or import scheduling."""

import json
from datetime import timedelta

from app.db.tenant import scope
from app.modules.accounts.models import StoreCredential, Workspace
from app.modules.auth.dependencies import now
from app.modules.finance import overview as finance_groups
from app.modules.finance.models import FinanceDay
from app.modules.insights import funnel, ozon_read
from app.modules.inventory.overview import overview as inventory
from app.modules.supplies.incoming import read as incoming
from app.modules.sync.models import SyncRun
from sqlalchemy import func, select


def finance(db, redis, vault, store, start, end, currency):
    if store.marketplace == "ozon":
        from app.modules.finance import ozon_read as reader

        result = reader.report(
            db, vault, store.workspace_id, store.id, start, end, currency, can_profit=False
        )
        return {
            "complete": result.period_covered and not result.is_partial,
            "groups": [row.model_dump() for row in result.groups],
        }
    if redis is None:
        return None
    from app.modules.finance.report import report

    result = report(db, redis, vault, store.workspace_id, store.id, start, end, currency, 1, 0)
    return {
        "complete": result.status == "ready" and result.period_covered and not result.is_partial,
        "groups": [row.model_dump() for row in finance_groups.build_groups(result.summary)],
    }


def read(db, redis, vault, store, today):
    """A short encrypted cache shares one read per cabinet between all recipients."""
    key = "perk:notification-facts:v1:" + str(store.id) + ":" + str(int(now().timestamp()) // 300)
    aad = "perk:notification-facts:v1:" + str(store.workspace_id) + ":" + str(store.id)
    if redis is not None:
        try:
            encrypted = redis.get(key)
            if encrypted:
                return json.loads(
                    vault.open(
                        encrypted.decode() if isinstance(encrypted, bytes) else encrypted, aad
                    )
                )
        except Exception:
            pass  # Cache failure cannot invent values or make the rule unavailable.
    currency = db.get(Workspace, store.workspace_id).currency
    start, end = today - timedelta(days=28), today - timedelta(days=1)
    reader = ozon_read.report if store.marketplace == "ozon" else funnel.report
    orders = reader(db, vault, store.workspace_id, store.id, start, end, product_limit=0)
    leaders = reader(db, vault, store.workspace_id, store.id, end, end, product_limit=3)
    stock = inventory(db, vault, store.workspace_id, [store], currency, False, limit=50000)
    positions = []
    for row in stock.items:
        product = row.product
        positions.append(
            {
                "id": product.id,
                "name": product.title or product.vendor_code,
                "units": row.fbo.units,
                "days": row.turnover_days,
                "status": row.turnover_status,
                "fresh": not row.fbo.stale
                and row.fbo.updated_at is not None
                and not stock.turnover_stale
                and not stock.turnover_loading,
            }
        )
    supplies = incoming(
        db, vault, store.workspace_id, store, today=today, lead_time_days=7, target_days=30
    )
    finance_end = end
    if store.marketplace == "wildberries":
        latest = db.scalar(
            select(func.max(FinanceDay.day)).where(*scope(FinanceDay, store.workspace_id, store.id))
        )
        if latest:
            finance_end = min(end, latest)
    finance_start = finance_end - timedelta(days=6)
    current = previous = None
    if finance_end >= end - timedelta(days=14):
        current = finance(db, redis, vault, store, finance_start, finance_end, currency)
        previous = finance(
            db,
            redis,
            vault,
            store,
            finance_start - timedelta(days=7),
            finance_start - timedelta(days=1),
            currency,
        )
    credential = db.scalar(
        select(StoreCredential).where(*scope(StoreCredential, store.workspace_id, store.id))
    )
    latest_run = db.scalar(
        select(SyncRun)
        .where(*scope(SyncRun, store.workspace_id, store.id), SyncRun.finished_at.is_not(None))
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )
    active = (
        db.scalar(
            select(SyncRun.id)
            .where(
                *scope(SyncRun, store.workspace_id, store.id),
                SyncRun.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        is not None
    )
    if store.marketplace == "ozon":
        from app.modules.catalog.marketplace_models import OzonCatalogSync
        from app.modules.insights.marketplace_models import OzonAnalyticsSync

        for model in (OzonAnalyticsSync, OzonCatalogSync):
            active |= (
                db.scalar(
                    select(model.store_id)
                    .where(
                        *scope(model, store.workspace_id, store.id),
                        model.status.in_(["pending", "queued", "running"]),
                    )
                    .limit(1)
                )
                is not None
            )
    stock_complete = (
        not stock.turnover_loading
        and not stock.turnover_stale
        and stock.fbo.updated_at is not None
        and not stock.fbo.stale
    )
    result = {
        "currency": orders.get("currency") or currency,
        "daily": orders["daily"],
        "leaders_day": str(end),
        "leaders": leaders["products"] if leaders["status"] == "ready" else [],
        "import_ready": (
            orders["status"] == "ready"
            and stock_complete
            and bool(current and current["complete"])
            and not active
        ),
        "stock": positions,
        "stock_complete": stock_complete,
        "supplies": supplies.raw if supplies.current else None,
        "finance": current,
        "previous_finance": previous,
        "finance_period": {"date_from": str(finance_start), "date_to": str(finance_end)},
        "stock_updated": stock.fbo.updated_at.isoformat() if stock.fbo.updated_at else None,
        "token_expires": credential.expires_at.isoformat()
        if credential and credential.expires_at
        else None,
        "connection_error": bool(
            latest_run
            and latest_run.status == "failed"
            and latest_run.finished_at > now() - timedelta(days=1)
        ),
        "connection_checked": bool(latest_run),
        "connection_stamp": latest_run.finished_at.isoformat() if latest_run else None,
    }
    if redis is not None:
        try:
            redis.set(key, vault.seal(json.dumps(result, default=str), aad), ex=300)
        except Exception:
            pass
    return result
