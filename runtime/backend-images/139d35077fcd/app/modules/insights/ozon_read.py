"""Read only confirmed daily aggregates. API requests schedule work, never wait for Ozon."""

import json
from collections import defaultdict
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.db.tenant import scope
from app.modules.accounts.models import Workspace
from app.modules.auth.dependencies import now
from app.modules.finance import realizations
from app.modules.insights.marketplace_models import (
    MarketplaceSalesDay,
    OzonAnalyticsSync,
)
from app.modules.insights.ozon_jobs import sales_aad
from app.modules.insights.ozon_sales import AMOUNT_FIELDS, AVAILABLE, combine
from app.modules.sync.schemas import moscow_today


def period(start, end):
    if start is None and end is None:
        end = moscow_today() - timedelta(days=1)
        start = end - timedelta(days=29)
    if (
        start is None
        or end is None
        or start > end
        or end > moscow_today()
        or (end - start).days >= 1100
    ):
        raise HTTPException(
            422, "Выберите обе даты периода, не длиннее трёх лет и без будущих дней."
        )
    if start < moscow_today() - timedelta(days=1099):
        raise HTTPException(422, "Для аналитики Ozon выберите последние три года.")
    return start, end


def ensure_range(db, workspace_id, store_id, start, source="sales"):
    """A scoped reader can request more history using the existing owner's import plan."""
    if source == "sales":
        ensure_range(db, workspace_id, store_id, start, source="traffic")
        ensure_range(db, workspace_id, store_id, start, source="finance")
    from sqlalchemy import text

    db.execute(
        text("SELECT perk_ozon_request_history(:ws,:sid,:src,:start,:end,false)"),
        {
            "ws": workspace_id,
            "sid": store_id,
            "src": source,
            "start": start,
            "end": moscow_today() - timedelta(days=1),
        },
    )


def report(
    db, vault, workspace_id, store_id, start, end, *, product_limit=500, price_basis="customer"
):
    saved = db.scalars(
        select(MarketplaceSalesDay)
        .where(
            *scope(MarketplaceSalesDay, workspace_id, store_id),
            MarketplaceSalesDay.day.between(start, end),
        )
        .order_by(MarketplaceSalesDay.day)
    ).all()
    rows = {
        row.day: json.loads(vault.open(row.ciphertext, sales_aad(workspace_id, store_id, row.day)))
        for row in saved
    }
    rows = {
        day: row
        for day, row in rows.items()
        if row.get("date_basis") == "in_process_at" and row.get("price_basis") == "customer_v1"
    }
    needs_prices = any(row.get("customer_prices_version") != 2 for row in rows.values())
    prices = realizations.prices(
        db,
        vault,
        workspace_id,
        store_id,
        [item["key"] for row in rows.values() for item in row["price_items"]],
    )
    from app.modules.insights.ozon_sales import reprice

    settlement_currency = db.get(Workspace, workspace_id).currency
    rows = {
        day: reprice(row, prices, settlement_currency, price_basis) for day, row in rows.items()
    }
    span = (end - start).days + 1
    currencies = {currency for row in rows.values() for currency in row["currencies"]}
    unpriced = any(row["totals"]["orders"] and not row["currencies"] for row in rows.values())
    currency = (
        next(iter(currencies))
        if len(currencies) == 1 and not unpriced
        else (db.get(Workspace, workspace_id).currency if not currencies and not unpriced else None)
    )
    unknown = combine([])
    daily, products = [], defaultdict(list)
    for index in range(span):
        day = start + timedelta(days=index)
        data = rows.get(day)
        values = dict(data["totals"] if data else unknown)
        if not currency:
            values.update(dict.fromkeys(AMOUNT_FIELDS))
        daily.append({"day": day.isoformat(), **values})
        if data:
            for sku, facts in data["products"].items():
                products[sku].append(facts)
    job = db.get(OzonAnalyticsSync, (workspace_id, store_id, "sales"))
    waiting = bool(job and job.error_code in {"ozon_report_preparing", "ozon_rate_limited"})
    error = job.error_code if job and not waiting else None
    active = bool(job and (job.status in {"pending", "queued", "running"} or waiting))
    loading = bool(len(rows) < span and job and not error and (active or job.cursor is not None))
    totals = combine(
        [row["totals"] for row in rows.values()],
        currency_known=bool(currency),
        allow_partial=True,
    )
    ranked = sorted(products, key=lambda sku: (-sum(row["orders"] for row in products[sku]), sku))
    from app.modules.insights.ozon_traffic import enrich
    from app.modules.insights.product_labels import enrich as product_labels

    product_rows = [
        {
            "nm_id": "",
            "id": str(uuid5(NAMESPACE_URL, f"perk:{store_id}:ozon:sku:{sku}")),
            "marketplace": "ozon",
            "marketplace_code": sku,
            "identifier_kind": "sku",
            **combine(products[sku], currency_known=bool(currency), allow_partial=True),
        }
        for sku in ranked
    ]
    coverage = {}
    available = enrich(
        db,
        vault,
        workspace_id,
        store_id,
        start,
        end,
        totals,
        daily,
        list(AVAILABLE),
        products=product_rows,
        sales_complete=len(rows) == span,
        coverage=coverage,
    )
    for item in product_rows:
        item.setdefault(
            "id", str(uuid5(NAMESPACE_URL, f"perk:{store_id}:ozon:sku:{item['marketplace_code']}"))
        )
    traffic_days = sum(row.get("opens") is not None for row in daily)

    def pending_source(source):
        task = db.get(OzonAnalyticsSync, (workspace_id, store_id, source))
        return bool(
            task
            and task.error_code in {None, "ozon_rate_limited", "ozon_report_preparing"}
            and (
                task.status in {"pending", "queued", "running"}
                or task.cursor is not None
                and task.cursor >= start
            )
        )

    loading = (
        loading
        or needs_prices
        or (
            (traffic_days < span or coverage.get("products", 0) < span)
            and pending_source("traffic")
        )
        or (bool(totals.get("partial_amounts")) and pending_source("finance"))
    )
    # Finish the expensive calculation before taking a short scheduling lock.
    # An existing backfill must keep its cursor; repeatedly rewinding it starves older days.
    if needs_prices and job and job.cursor is None and not active:
        from sqlalchemy import text

        db.execute(
            text("SELECT perk_ozon_request_history(:ws,:sid,'sales',:start,:end,true)"),
            {"ws": workspace_id, "sid": store_id, "start": start, "end": end},
        )
    return {
        "history_available_from": None,
        "available_days": span,
        "traffic_known_days": traffic_days,
        "product_traffic_known_days": coverage.get("products", 0),
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "data_source": "ozon_postings",
        "available_metrics": available,
        "error_code": error,
        "is_loading": loading,
        "status": "ready" if len(rows) == span else "partial" if rows else "no_data",
        "known_days": len(rows),
        "period_days": span,
        "currency": currency,
        "buyouts_by": "order_date",
        "buyouts_maturing_from": max(start, moscow_today() - timedelta(days=28)).isoformat()
        if end >= moscow_today() - timedelta(days=28)
        else None,
        "totals": totals,
        "partial_amounts": totals.get("partial_amounts", []),
        "daily": daily,
        "products": product_labels(
            product_rows[:product_limit],
            db,
            vault,
            workspace_id,
            store_id,
            "ozon",
        ),
        "products_truncated": product_limit is not None and len(product_rows) > product_limit,
        "freshness": {
            "computed_at": min((row.updated_at for row in saved if row.day in rows), default=now()),
            "stale": not error and (active or loading),
        },
    }


def summary(db, vault, workspace_id, store_id, start, end, price_basis="customer"):
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - (end - start)
    ensure_range(db, workspace_id, store_id, previous_start)
    current = report(db, vault, workspace_id, store_id, start, end, price_basis=price_basis)
    before = report(
        db, vault, workspace_id, store_id, previous_start, previous_end, price_basis=price_basis
    )
    complete = current["status"] == before["status"] == "ready"
    currency = current["currency"] if current["currency"] == before["currency"] else None
    if not currency:
        for period_report in (current, before):
            period_report["totals"].update(dict.fromkeys(AMOUNT_FIELDS))
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "status": "ready" if complete else "error" if current["error_code"] else "preparing",
        "data_source": "ozon_postings",
        "currency": currency,
        "totals": current["totals"],
        "partial_amounts": current.get("partial_amounts", []),
        "previous": {
            "date_from": previous_start.isoformat(),
            "date_to": previous_end.isoformat(),
            "totals": before["totals"],
            "partial_amounts": before.get("partial_amounts", []),
        },
        "error_code": current["error_code"],
        "freshness": current["freshness"],
    }
