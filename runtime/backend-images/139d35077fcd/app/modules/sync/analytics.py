"""Incremental encrypted daily aggregates; every cache read follows authorization and RLS."""

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from redis.exceptions import RedisError
from sqlalchemy import and_, delete, or_, select, tuple_

from app.integrations.wildberries.data import CHANGE_FEEDS, DATED, METRIC_SOURCES, Source
from app.modules.auth.dependencies import now
from app.modules.finance.facts import facts, report_sale, sale_day
from app.modules.finance.precision import money_precision
from app.modules.sync.models import (
    SyncRun,
    WBDailyMetric,
    WBMetricVersion,
    WBRecord,
    WBStagedRecord,
)
from app.modules.sync.schemas import FINANCE_START, history_limits, moscow_today

# 3: finance sales/returns are also aggregated by sale date (report_bydate_*).
METRIC_FORMAT = 5
FUNNEL_FIELDS = (
    "open_count",
    "cart_count",
    "order_count",
    "buyout_count",
    "cancel_count",
    "wishlist_count",
)


def record_context(workspace_id, store_id, source, key):
    return f"wb-data:v1:{workspace_id}:{store_id}:{source}:{key}"


def metric_context(workspace_id, store_id, source, dataset, day, nm_id, currency):
    return f"wb-metric:v1:{workspace_id}:{store_id}:{source}:{dataset}:{day}:{nm_id}:{currency}"


def customer_sale(row):
    # Operational counters exclude bookkeeping corrections. Finance facts reconcile them.
    if row.get("operation", "").strip().casefold() in {"продажа", "возврат"}:
        return report_sale(row)
    return None


def contribution(source, row):
    values = defaultdict(Decimal)
    values["records"] = Decimal(1)
    if source == Source.SALES:
        day, currency = date.fromisoformat(row["date"][:10]), "WB"
        kind = "returns" if row["kind"] == "return" else "sales"
        values[kind] = Decimal(1)
        amount = row.get("finished_price")
        values[kind + "_amount"] = abs(Decimal(amount)) if amount is not None else Decimal(0)
        values["missing_prices"] = Decimal(amount is None)
    elif source == Source.ORDERS:
        # Order day; a later cancellation replaces the record and moves it between fields.
        day, currency = date.fromisoformat(row["date"][:10]), "WB"
        amount = row.get("finished_price")
        price = abs(Decimal(amount)) if amount is not None else Decimal(0)
        values["orders"], values["orders_amount"] = Decimal(1), price
        values["missing_prices"] = Decimal(amount is None)
        if row["is_cancel"]:
            values["cancellations"], values["cancellations_amount"] = Decimal(1), price
    elif source == Source.FUNNEL:
        # WB funnel day: buyouts and cancellations are attributed to the ORDER day.
        day, currency = date.fromisoformat(row["day"]), row["currency"]
        for field in FUNNEL_FIELDS:
            values[field] = Decimal(row[field])
        for field in ("order_sum", "buyout_sum", "cancel_sum"):
            amount = row.get(field)
            values[field] = Decimal(amount) if amount is not None else Decimal(0)
            values["missing_" + field] = Decimal(amount is None)
    else:
        day, currency = date.fromisoformat(row["report_date"][:10]), row["currency"]
        values["quantity"] = Decimal(row["quantity"])
        values["report_records"] = Decimal(0)
        sale = customer_sale(row)
        if sale:
            kind, quantity = sale
            values["report_records"] = Decimal(1)
            values["report_" + kind] = Decimal(quantity)
            amount = row.get("retail_amount")
            values["report_" + kind + "_amount"] = (
                abs(Decimal(amount)) if amount is not None else Decimal(0)
            )
            values["report_missing_prices"] = Decimal(amount is None)
        elif row.get("operation", "").strip().casefold() in {
            "корректная продажа",
            "корректный возврат",
            "сторно продаж",
            "сторно возвратов",
            "коррекция продаж",
            "коррекция возвратов",
        }:
            values["report_correction_records"] = Decimal(1)
        elif row.get("operation", "").strip().casefold() in {"продажа", "возврат"}:
            values["report_invalid_sales_records"] = Decimal(1)
        returned = row["document_type"].strip().casefold() == "возврат"
        for field in ("retail_amount", "for_pay", "acquiring_fee"):
            amount = row.get(field)
            value = Decimal(amount) if amount is not None else Decimal(0)
            values[field] = -abs(value) if returned else value
            values["missing_" + field] = Decimal(amount is None)
    return (day, row["nm_id"], currency), dict(values)


def sale_date_contribution(source, row):
    """A report sale/return also counted on its sale date (saleDt), not the report date.

    WB includes a sale in a weekly report days after it happened; for buyouts by day the
    sale date is the true event date. Rows without a sale date fall back to the report
    date and are counted in report_bydate_missing_dates. Fields use the report_ prefix,
    so they never enter financial totals.
    """
    if source != Source.FINANCE or not (sale := customer_sale(row)):
        return None
    kind, quantity = sale
    day = sale_day(row)
    amount = row.get("retail_amount")
    values = {
        "report_bydate_records": Decimal(1),
        "report_bydate_" + kind: Decimal(quantity),
        "report_bydate_" + kind + "_amount": abs(Decimal(amount))
        if amount is not None
        else Decimal(0),
        "report_bydate_missing_prices": Decimal(amount is None),
        "report_bydate_missing_dates": Decimal(not day),
    }
    day = date.fromisoformat(day) if day else date.fromisoformat(row["report_date"][:10])
    return (day, row["nm_id"], row["currency"]), values


@money_precision()
def apply_deltas(db, vault, run, rows, dataset="published"):
    deltas = defaultdict(lambda: defaultdict(Decimal))
    for record_key, new_ciphertext, old_ciphertext in rows:
        aad = record_context(run.workspace_id, run.store_id, run.source, record_key)
        for ciphertext, sign in ((old_ciphertext, -1), (new_ciphertext, 1)):
            if ciphertext is None:
                continue
            record = json.loads(vault.open(ciphertext, aad))
            key, values = contribution(run.source, record)
            if run.source == Source.FINANCE and dataset != "published":
                # Same monetary rules as the final report; original-sale costs wait for publication.
                (day, currency), _, financial = facts(record, {})
                key = day, record["nm_id"], currency
                values.update({"profit_" + field: value for field, value in financial.items()})
            for field, value in values.items():
                deltas[key][field] += value * sign
            if extra := sale_date_contribution(run.source, record):
                for field, value in extra[1].items():
                    deltas[extra[0]][field] += value * sign
    existing = (
        db.scalars(
            select(WBDailyMetric).where(
                WBDailyMetric.workspace_id == run.workspace_id,
                WBDailyMetric.store_id == run.store_id,
                WBDailyMetric.source == run.source,
                WBDailyMetric.dataset == dataset,
                tuple_(WBDailyMetric.day, WBDailyMetric.nm_id, WBDailyMetric.currency).in_(
                    list(deltas)
                ),
            )
        ).all()
        if deltas
        else []
    )
    by_key = {(row.day, row.nm_id, row.currency): row for row in existing}
    for (day, nm_id, currency), delta in deltas.items():
        pk = (run.workspace_id, run.store_id, run.source, dataset, day, nm_id, currency)
        row = by_key.get((day, nm_id, currency))
        aad = metric_context(*pk)
        previous = json.loads(vault.open(row.ciphertext, aad)) if row else {}
        values = {field: Decimal(value) for field, value in previous.items()}
        for field, value in delta.items():
            values[field] = values.get(field, Decimal(0)) + value
        if not row:
            row = WBDailyMetric(
                workspace_id=run.workspace_id,
                store_id=run.store_id,
                source=run.source,
                dataset=dataset,
                day=day,
                nm_id=nm_id,
                currency=currency,
            )
            db.add(row)
        row.ciphertext = vault.seal(
            json.dumps(
                {key: format(value, "f") for key, value in values.items()}, separators=(",", ":")
            ),
            aad,
        )
    db.flush()


def update_metrics(db, vault, run):
    if run.source not in DATED:
        return
    rebuild_store(db, vault, run.workspace_id, run.store_id)
    if run.source in METRIC_SOURCES:
        apply_staged(db, vault, run)
    # Record-based reports (returns) depend on the same revision as aggregate ones.
    version = db.get(WBMetricVersion, (run.workspace_id, run.store_id))
    version.version, version.updated_at = uuid4(), now()


def apply_staged(db, vault, run):
    last_key = ""
    # Keyset batches avoid retaining an entire financial page in SQLAlchemy's identity map.
    while True:
        rows = db.execute(
            select(WBStagedRecord.record_key, WBStagedRecord.ciphertext, WBRecord.ciphertext)
            .outerjoin(
                WBRecord,
                and_(
                    WBRecord.workspace_id == WBStagedRecord.workspace_id,
                    WBRecord.store_id == WBStagedRecord.store_id,
                    WBRecord.source == run.source,
                    WBRecord.record_key == WBStagedRecord.record_key,
                ),
            )
            .where(
                WBStagedRecord.workspace_id == run.workspace_id,
                WBStagedRecord.store_id == run.store_id,
                WBStagedRecord.run_id == run.id,
                WBStagedRecord.record_key > last_key,
            )
            .order_by(WBStagedRecord.record_key)
            .limit(500)
        ).all()
        if not rows:
            break
        apply_deltas(db, vault, run, rows)
        last_key = rows[-1][0]
    if run.source == Source.FUNNEL:
        retire_missing(db, vault, run)


def retire_missing(db, vault, run):
    """A funnel run is the complete picture of its days: idle cards are not sent, so a
    published record of those days that is absent now is removed and subtracted."""
    if run.date_from is None or run.date_to is None:
        return
    staged = select(WBStagedRecord.record_key).where(
        WBStagedRecord.workspace_id == run.workspace_id,
        WBStagedRecord.store_id == run.store_id,
        WBStagedRecord.run_id == run.id,
        WBStagedRecord.record_key == WBRecord.record_key,
    )
    in_range = (
        WBRecord.workspace_id == run.workspace_id,
        WBRecord.store_id == run.store_id,
        WBRecord.source == run.source,
        WBRecord.record_key >= f"{run.date_from.isoformat()}:",
        WBRecord.record_key < f"{(run.date_to + timedelta(days=1)).isoformat()}:",
        ~staged.exists(),
    )
    while True:
        rows = db.execute(
            select(WBRecord.record_key, WBRecord.ciphertext).where(*in_range).limit(500)
        ).all()
        if not rows:
            return
        apply_deltas(db, vault, run, [(key, None, ciphertext) for key, ciphertext in rows])
        db.execute(
            delete(WBRecord).where(
                WBRecord.workspace_id == run.workspace_id,
                WBRecord.store_id == run.store_id,
                WBRecord.source == run.source,
                WBRecord.record_key.in_([key for key, _ in rows]),
            )
        )


def ensure_preview(db, vault, run):
    if run.source not in METRIC_SOURCES:
        return
    preview = db.scalars(
        select(WBDailyMetric)
        .where(
            WBDailyMetric.workspace_id == run.workspace_id,
            WBDailyMetric.store_id == run.store_id,
            WBDailyMetric.source == run.source,
            WBDailyMetric.dataset == str(run.id),
        )
        .execution_options(yield_per=100)
    )
    existing = False
    for cell in preview:
        existing = True
        if run.source != Source.FINANCE:
            return
        aad = metric_context(
            run.workspace_id,
            run.store_id,
            run.source,
            str(run.id),
            cell.day,
            cell.nm_id,
            cell.currency,
        )
        fields = json.loads(vault.open(cell.ciphertext, aad))
        if "records" not in fields:
            # Sale-date-only cell: the format check needs a report-date cell.
            continue
        if "profit_records" in fields and "profit_detail_v4_records" in fields:
            return
        break
    if existing:
        # Upgrade an in-flight preview once in a worker, never on a chart read.
        discard_preview(db, run)
    last_key = ""
    while True:
        rows = db.execute(
            select(WBStagedRecord.record_key, WBStagedRecord.ciphertext)
            .where(
                WBStagedRecord.workspace_id == run.workspace_id,
                WBStagedRecord.store_id == run.store_id,
                WBStagedRecord.run_id == run.id,
                WBStagedRecord.record_key > last_key,
            )
            .order_by(WBStagedRecord.record_key)
            .limit(500)
        ).all()
        if not rows:
            break
        apply_deltas(
            db, vault, run, [(key, ciphertext, None) for key, ciphertext in rows], str(run.id)
        )
        last_key = rows[-1][0]
    run.preview_updated_at = now()


def stage_metrics(db, vault, run, values):
    if run.source not in METRIC_SOURCES:
        return
    # Caller holds the store lock. Upgrade old financial aggregates before applying deltas.
    if run.source == Source.FINANCE:
        rebuild_store(db, vault, run.workspace_id, run.store_id)
    ensure_preview(db, vault, run)
    for offset in range(0, len(values), 500):
        batch = values[offset : offset + 500]
        old = dict(
            db.execute(
                select(WBStagedRecord.record_key, WBStagedRecord.ciphertext).where(
                    WBStagedRecord.run_id == run.id,
                    WBStagedRecord.workspace_id == run.workspace_id,
                    WBStagedRecord.store_id == run.store_id,
                    WBStagedRecord.record_key.in_([value["record_key"] for value in batch]),
                )
            ).all()
        )
        apply_deltas(
            db,
            vault,
            run,
            [
                (value["record_key"], value["ciphertext"], old.get(value["record_key"]))
                for value in batch
            ],
            str(run.id),
        )
    run.preview_updated_at = now()


def discard_preview(db, run):
    db.execute(
        delete(WBDailyMetric).where(
            WBDailyMetric.workspace_id == run.workspace_id,
            WBDailyMetric.store_id == run.store_id,
            WBDailyMetric.dataset == str(run.id),
        )
    )


def datasets(db, workspace_id, store_id):
    selected, fingerprints = {}, []
    for source in (Source.SALES, Source.FINANCE):
        base = (
            select(SyncRun)
            .execution_options(populate_existing=True)
            .where(
                SyncRun.workspace_id == workspace_id,
                SyncRun.store_id == store_id,
                SyncRun.source == source,
            )
        )
        success = db.scalar(base.where(SyncRun.status == "succeeded").limit(1))
        latest = db.scalar(base.order_by(SyncRun.created_at.desc()).limit(1))
        selected[source] = (
            str(latest.id)
            if not success and latest and latest.status in {"queued", "running"}
            else "published"
        )
        if selected[source] != "published":
            fingerprints.append(f"{source}:{latest.id}:{latest.pages_processed}")
    return selected, ":".join(fingerprints)


def abc_rows(products, limit):
    ranked = sorted(
        (
            (sku, max(Decimal(0), values["sales"] - values["returns"]))
            for sku, values in products.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    total = sum((value for _, value in ranked), Decimal(0))
    result, cumulative = [], Decimal(0)
    for nm_id, quantity in ranked:
        if quantity <= 0:
            continue
        before = cumulative / total
        cumulative += quantity
        result.append(
            {
                "nm_id": nm_id,
                "net_units": int(quantity),
                "share_percent": format(quantity / total * 100, ".2f"),
                "cumulative_percent": format(cumulative / total * 100, ".2f"),
                "class": "A"
                if before < Decimal("0.80")
                else "B"
                if before < Decimal("0.95")
                else "C",
            }
        )
    return result[:limit], len(result)


@money_precision()
def calculate(db, vault, workspace_id, store_id, start, end, limit, selected, sales_basis="auto"):
    basis = (
        ("reports" if start < history_limits()[Source.SALES]["date_from"] else "operational")
        if sales_basis == "auto"
        else sales_basis
    )
    days = defaultdict(lambda: defaultdict(Decimal))
    products = defaultdict(lambda: defaultdict(Decimal))
    finance = defaultdict(lambda: defaultdict(Decimal))
    financial_days = defaultdict(lambda: defaultdict(Decimal))
    sales = defaultdict(Decimal)
    report_money = defaultdict(lambda: defaultdict(Decimal))
    corrections, invalid_sales = Decimal(0), Decimal(0)
    version = db.get(WBMetricVersion, (workspace_id, store_id))
    ready = basis == "operational" or bool(version and version.format_version >= METRIC_FORMAT)
    rows = db.scalars(
        select(WBDailyMetric)
        .where(
            WBDailyMetric.workspace_id == workspace_id,
            WBDailyMetric.store_id == store_id,
            WBDailyMetric.day.between(start, end),
            or_(
                *(
                    and_(WBDailyMetric.source == source, WBDailyMetric.dataset == dataset)
                    for source, dataset in selected.items()
                )
            ),
        )
        .execution_options(yield_per=500)
    )
    for row in rows:
        aad = metric_context(
            workspace_id, store_id, row.source, row.dataset, row.day, row.nm_id, row.currency
        )
        values = {
            field: value
            for field, value in json.loads(vault.open(row.ciphertext, aad)).items()
            if not field.startswith("report_bydate_")
        }
        if not values:
            # Sale-date buyout cell only: it belongs to the buyouts report, not to this one.
            continue
        targets = (
            (finance[row.currency], financial_days[(row.day.isoformat(), row.currency)])
            if row.source == Source.FINANCE
            else ()
        )
        if row.source == Source.SALES and basis == "operational":
            targets = (sales, days[row.day.isoformat()], products[row.nm_id])
        for field, value in values.items():
            for target in targets:
                target[field] += Decimal(value)
        if row.source == Source.FINANCE and basis == "reports" and ready:
            corrections += Decimal(values.get("report_correction_records", 0))
            invalid_sales += Decimal(values.get("report_invalid_sales_records", 0))
            if Decimal(values.get("report_records", 0)):
                for field in ("sales", "returns", "missing_prices"):
                    value = Decimal(values.get("report_" + field, 0))
                    for target in (sales, days[row.day.isoformat()], products[row.nm_id]):
                        target[field] += value
                for field in ("sales_amount", "returns_amount"):
                    report_money[row.currency][field] += Decimal(values.get("report_" + field, 0))

    def sales_value(value):
        return {
            "sales": int(value["sales"]),
            "returns": int(value["returns"]),
            "net_units": int(value["sales"] - value["returns"]),
            "sales_amount": format(value["sales_amount"], "f"),
            "returns_amount": format(value["returns_amount"], "f"),
            "net_amount": format(value["sales_amount"] - value["returns_amount"], "f"),
            "missing_prices": int(value["missing_prices"]),
        }

    abc, product_count = abc_rows(products, limit)
    result = {
        "sales": sales_value(sales),
        "daily": [{"day": day, **sales_value(days[day])} for day in sorted(days)],
        "financial_daily": [
            {"day": day, "currency": currency, "for_pay": format(values["for_pay"], "f")}
            for (day, currency), values in sorted(financial_days.items())
        ],
        "abc": abc,
        "abc_product_count": product_count,
        "abc_metric": "net_units",
        "abc_thresholds": [80, 95],
        "finance": [
            {
                "currency": currency,
                **{
                    field: int(value)
                    if field.startswith("missing_") or field in {"records", "quantity"}
                    else format(value, "f")
                    for field, value in values.items()
                    if not field.startswith(("report_", "profit_"))
                },
            }
            for currency, values in sorted(finance.items())
        ],
        "preliminary": True,
        "sales_basis": basis,
        "sales_date_basis": "report_date" if basis == "reports" else "event_date",
        "sales_metrics_ready": ready,
        "sales_money": [
            {
                "currency": currency,
                **{
                    field: amount
                    for field, amount in sales_value(value).items()
                    if field in {"sales_amount", "returns_amount", "net_amount"}
                },
            }
            for currency, value in sorted(report_money.items())
        ],
        "sales_quality": {
            "correction_records": int(corrections),
            "invalid_records": int(invalid_sales),
            "corrections_in_customer_counts": False,
        },
        "partial_sources": [
            source for source, dataset in selected.items() if dataset != "published"
        ],
    }
    if basis == "reports":
        # Different currencies must never be combined into a fictitious scalar amount.
        for value in [result["sales"], *result["daily"]]:
            for field in ("sales_amount", "returns_amount", "net_amount"):
                value[field] = None
    return result


def cache_address(vault, workspace_id, store_id, version, start, end, limit, sales_basis="auto"):
    aad = f"wb-dashboard:v3:{workspace_id}:{store_id}:{version}:{start}:{end}:{limit}:{sales_basis}"
    return "perk:dashboard:" + vault.digest("dashboard", aad), aad


def metric_snapshot(db, workspace_id, store_id):
    row = db.get(WBMetricVersion, (workspace_id, store_id), populate_existing=True)
    version = SimpleNamespace(version=row.version, updated_at=row.updated_at) if row else None
    selected, fingerprint = datasets(db, workspace_id, store_id)
    revision = f"{version.version if version else 'initial'}:{fingerprint}"
    return version, selected, revision


def cached_metrics(
    db, redis, vault, workspace_id, store_id, start, end, limit=100, sales_basis="auto"
):
    # Optimistic revision checks let cached reads proceed during a long import transaction.
    # Only an unchanged publication/preview revision can populate its cache entry.
    for _ in range(3):
        version, selected, revision = metric_snapshot(db, workspace_id, store_id)
        key, aad = cache_address(
            vault, workspace_id, store_id, revision, start, end, limit, sales_basis
        )
        result, hit = None, False
        try:
            encrypted = redis.get(key)
            if isinstance(encrypted, (str, bytes)):
                result = json.loads(
                    vault.open(
                        encrypted.decode() if isinstance(encrypted, bytes) else encrypted, aad
                    )
                )
                hit = True
        except RedisError, InvalidTag, ValueError, KeyError:
            pass
        if result is None:
            result = calculate(
                db, vault, workspace_id, store_id, start, end, limit, selected, sales_basis
            )
        _, _, after = metric_snapshot(db, workspace_id, store_id)
        if revision != after:
            continue
        result["snapshot_stable"] = True
        if not hit:
            try:
                redis.set(key, vault.seal(json.dumps(result, separators=(",", ":")), aad), ex=900)
            except RedisError:
                pass
        return result, version
    # Continuous concurrent updates must never be presented as a complete stable period.
    result["snapshot_stable"] = False
    return result, version


def coverage(db, workspace_id, store_id):
    result = {}
    for source in (Source.SALES, Source.ORDERS, Source.FINANCE, Source.FUNNEL, Source.RETURNS):
        runs = db.scalars(
            select(SyncRun)
            .where(
                SyncRun.workspace_id == workspace_id,
                SyncRun.store_id == store_id,
                SyncRun.source == source,
                SyncRun.status == "succeeded",
            )
            .order_by(SyncRun.date_from)
        ).all()
        merged = []
        for run in runs:
            # A sales change-cursor refresh proves changes, not a complete 90-day download.
            if source in CHANGE_FEEDS and run.sync_mode == "incremental":
                continue
            if run.date_from is None or run.date_to is None:
                continue
            if merged and run.date_from <= merged[-1][1] + timedelta(days=1):
                merged[-1][1] = max(merged[-1][1], run.date_to)
            else:
                merged.append([run.date_from, run.date_to])
        result[source] = [
            {"date_from": start.isoformat(), "date_to": end.isoformat()} for start, end in merged
        ]
    return result


def known_days(db, workspace_id, store_id, source):
    """(first, last) known day of a WB change-feed report (sales or orders), or (None, None).

    Known = on or after the start of the first complete (non-incremental) download
    and fully ended before the latest successful import. After a complete download,
    incremental runs follow WB's change feed, so they keep later days current.
    """
    windows = coverage(db, workspace_id, store_id)[source]
    latest = db.scalar(
        select(SyncRun.finished_at)
        .where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.store_id == store_id,
            SyncRun.source == source,
            SyncRun.status == "succeeded",
        )
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )
    if not windows or latest is None:
        return None, None
    first = date.fromisoformat(windows[0]["date_from"])
    through = (latest + timedelta(hours=3)).date() - timedelta(days=1)
    return first, through


def warm_store(db, redis, vault, workspace_id, store_id):
    rebuild_store(db, vault, workspace_id, store_id)
    today = moscow_today() - timedelta(days=1)
    for days in (7, 30, 90, 365, 730):
        floor = FINANCE_START
        cached_metrics(
            db,
            redis,
            vault,
            workspace_id,
            store_id,
            max(floor, today - timedelta(days=days - 1)),
            today,
        )
    cached_metrics(db, redis, vault, workspace_id, store_id, FINANCE_START, today)
    version = db.get(WBMetricVersion, (workspace_id, store_id))
    if version:
        version.warmed_version = version.version


def rebuild_store(db, vault, workspace_id, store_id):
    """Upgrade encrypted metrics atomically from retained rows, under the store lock.

    A failed transaction leaves the previous metrics and version intact. No WB re-download.
    """
    version = db.get(WBMetricVersion, (workspace_id, store_id))
    if version and version.format_version >= METRIC_FORMAT:
        return
    sources = (
        (Source.FINANCE,)
        if version
        else (Source.SALES, Source.ORDERS, Source.FINANCE, Source.FUNNEL)
    )
    for source in sources:
        db.execute(
            delete(WBDailyMetric).where(
                WBDailyMetric.workspace_id == workspace_id,
                WBDailyMetric.store_id == store_id,
                WBDailyMetric.source == source,
            )
        )
        run = type(
            "MetricRun", (), dict(workspace_id=workspace_id, store_id=store_id, source=source)
        )()
        last_key = ""
        while True:
            rows = db.execute(
                select(WBRecord.record_key, WBRecord.ciphertext)
                .where(
                    WBRecord.workspace_id == workspace_id,
                    WBRecord.store_id == store_id,
                    WBRecord.source == source,
                    WBRecord.record_key > last_key,
                )
                .order_by(WBRecord.record_key)
                .limit(500)
            ).all()
            if not rows:
                break
            apply_deltas(db, vault, run, [(key, ciphertext, None) for key, ciphertext in rows])
            last_key = rows[-1][0]
    if not version:
        version = WBMetricVersion(workspace_id=workspace_id, store_id=store_id)
        db.add(version)
    version.version, version.updated_at, version.format_version = uuid4(), now(), METRIC_FORMAT
    db.flush()
    for run in db.scalars(
        select(SyncRun).where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.store_id == store_id,
            SyncRun.source.in_(sources),
            SyncRun.status.in_(["queued", "running"]),
        )
    ).all():
        ensure_preview(db, vault, run)
