"""Report-date estimates with exact money, explicit gaps and no second commission deduction."""

import json
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.finance.categories import render_details
from app.modules.finance.facts import EXPENSE_FIELDS, INCLUDED_FIELDS, UNRECONCILED_FIELDS
from app.modules.finance.models import ExternalExpense, FinanceDay, FinanceProjection, ProductCost
from app.modules.finance.precision import money_precision
from app.modules.finance.projection import READABLE_FORMATS, day_aad, source_run
from app.modules.finance.schemas import (
    ABCItem,
    ProfitABC,
    ProfitDay,
    ProfitProduct,
    ProfitReport,
    ProfitValues,
)
from app.modules.finance.service import expense_view, unit_amount
from app.modules.sync.analytics import coverage, metric_context
from app.modules.sync.models import SyncRun, WBDailyMetric


def covered_period(db, workspace_id, store_id, start, end):
    cursor = start
    for interval in coverage(db, workspace_id, store_id)["finance"]:
        left, right = (
            date.fromisoformat(interval["date_from"]),
            date.fromisoformat(interval["date_to"]),
        )
        if left > cursor:
            return False
        if right >= cursor:
            if right >= end:
                return True
            cursor = right + timedelta(days=1)
        if cursor > end:
            return True
    return False


class PriceBook(dict):
    """(nm_id, barcode, currency) → [(effective_from, amount)] sorted by date, with indexes
    built once: sorted dates per key and the first date of any size price per article."""

    def __init__(self, entries=()):
        super().__init__(entries)
        self.dates = {key: [entry[0] for entry in history] for key, history in self.items()}
        self.variants_from = {}
        for (nm_id, barcode, currency), history in self.items():
            if barcode and history:
                key = (nm_id, currency)
                first = history[0][0]
                if key not in self.variants_from or first < self.variants_from[key]:
                    self.variants_from[key] = first


def price_book(db, vault, workspace_id, store_id, identifiers):
    book = defaultdict(list)
    identifiers = sorted(identifiers)
    for offset in range(0, len(identifiers), 500):
        rows = db.scalars(
            select(ProductCost)
            .where(
                *scope(ProductCost, workspace_id, store_id),
                ProductCost.nm_id.in_(identifiers[offset : offset + 500]),
            )
            .order_by(ProductCost.effective_from)
        ).all()
        for row in rows:
            book[(row.nm_id, row.barcode, row.currency)].append(
                (row.effective_from, unit_amount(vault, row))
            )
    return PriceBook(book)


def price_for(book, item, currency):
    """O(log n) per lookup. Same rules as before, without scanning every price key."""
    if not item["cost_day"]:
        return None
    if not isinstance(book, PriceBook):
        book = PriceBook(book)
    at = date.fromisoformat(item["cost_day"])
    # An absent source barcode cannot silently choose the general price when a size override exists.
    if not item["barcode"]:
        variants_from = book.variants_from.get((item["nm_id"], currency))
        if variants_from is not None and variants_from <= at:
            return None
    for barcode in [item["barcode"], ""] if item["barcode"] else [""]:
        key = (item["nm_id"], barcode, currency)
        index = bisect_right(book.dates.get(key, []), at) - 1
        if index >= 0:
            return book[key][index][1]
    return None


def accumulator():
    return defaultdict(Decimal)


def add_group(target, values, cost):
    for field, value in values.items():
        target[field] += Decimal(value)
    quantities = Decimal(values.get("sales", 0)) + Decimal(values.get("returns", 0))
    if quantities:
        if cost is None:
            target["missing_cost_units"] += quantities
        else:
            target["cogs"] += cost * (
                Decimal(values.get("sales", 0)) - Decimal(values.get("returns", 0))
            )


def render_values(value, period_covered):
    required_missing = {
        "missing_cost_units",
        "missing_for_pay",
        "missing_retail_amount",
        *("missing_" + field for field in EXPENSE_FIELDS),
    }
    issues = {
        field: int(count)
        for field, count in value.items()
        if count
        and (
            field in required_missing
            or field
            in {
                "legacy_records",
                "unclassified_operation",
                "unclassified_revenue",
                "ambiguous_expense_sign",
                "unreconciled_adjustment",
                "unexpected_customer_amount_sign",
                "unavailable_report_currency",
            }
        )
    }
    if not period_covered:
        issues["incomplete_period"] = 1
    amounts_known = not any(
        field in issues
        for field in (
            "missing_for_pay",
            *("missing_" + field for field in EXPENSE_FIELDS),
            "unclassified_operation",
            "ambiguous_expense_sign",
            "unreconciled_adjustment",
            "legacy_records",
            "unexpected_customer_amount_sign",
        )
    )
    settlement = (
        value["for_pay"] - sum(value[field] for field in EXPENSE_FIELDS) if amounts_known else None
    )
    cogs = value["cogs"] if not value["missing_cost_units"] else None
    contribution = (
        settlement - cogs if settlement is not None and cogs is not None and not issues else None
    )
    profit = contribution - value["external_expenses"] if contribution is not None else None
    # Old aggregates remain conservative until the worker rebuilds their format.
    unknown_revenue = value.get("unclassified_revenue", value.get("unclassified_operation", 0))
    revenue = (
        value["retail_amount"]
        if not unknown_revenue
        and not any(
            value[field]
            for field in (
                "missing_retail_amount",
                "unexpected_customer_amount_sign",
                "unavailable_report_currency",
            )
        )
        else None
    )
    return ProfitValues(
        records=int(value["records"]),
        sales=int(value["sales"]),
        returns=int(value["returns"]),
        net_units=int(value["sales"] - value["returns"]),
        revenue=format(revenue, "f") if revenue is not None else None,
        for_pay=format(value["for_pay"], "f") if not value["missing_for_pay"] else None,
        wb_expenses={
            field: format(value[field], "f") if not value["missing_" + field] else None
            for field in EXPENSE_FIELDS
        },
        included_components={
            field: format(value[field], "f") if not value["missing_" + field] else None
            for field in INCLUDED_FIELDS
        },
        unreconciled_components={
            field: format(value[field], "f") if not value["missing_" + field] else None
            for field in UNRECONCILED_FIELDS
        },
        settlement_estimate=format(settlement, "f")
        if settlement is not None and not issues.get("incomplete_period")
        else None,
        cogs=format(cogs, "f") if cogs is not None else None,
        contribution_before_external_expenses=format(contribution, "f")
        if contribution is not None
        else None,
        external_expenses=format(value["external_expenses"], "f"),
        profit_before_tax=format(profit, "f") if profit is not None else None,
        margin_percent=format(profit / revenue * 100, ".4f")
        if profit is not None and revenue is not None and revenue > 0
        else None,
        issues=issues,
        calculation_complete=not issues,
        financial_details=render_details(value, settlement, cogs, value["external_expenses"]),
    )


def add_expenses(db, vault, workspace_id, store_id, start, end, currency, total, days):
    expenses = db.scalars(
        select(ExternalExpense)
        .where(
            *scope(ExternalExpense, workspace_id, store_id),
            ExternalExpense.deleted_at.is_(None),
            ExternalExpense.currency == currency,
            ExternalExpense.expense_date.between(start, end),
        )
        .limit(10001)
    ).all()
    if len(expenses) > 10000:
        raise HTTPException(422, "Слишком много внешних расходов. Уточните период.")
    for row in expenses:
        expense = expense_view(vault, row)
        amount = Decimal(expense.amount)
        total["detail_external_" + expense.category] += amount
        days[row.expense_date]["detail_external_" + expense.category] += amount
        total["external_expenses"] += amount
        days[row.expense_date]["external_expenses"] += amount


def published_groups(db, vault, workspace_id, store_id, start, end, currency):
    groups = []
    for row in db.scalars(
        select(FinanceDay)
        .where(
            *scope(FinanceDay, workspace_id, store_id),
            FinanceDay.day.between(start, end),
            FinanceDay.currency == currency,
        )
        .order_by(FinanceDay.day)
    ):
        for item in json.loads(
            vault.open(row.ciphertext, day_aad(workspace_id, store_id, row.day, row.currency))
        ):
            groups.append((row.day, item))
    return groups


@money_precision()
def partial_report(
    db, vault, workspace_id, store_id, start, end, currency, limit, offset, run, published=None
):
    """Read encrypted daily aggregates, never staged records or the provider API.

    With a published projection, each day comes from exactly one source: the running
    import where it already has rows for that day, otherwise the published dataset.
    Amounts of the same day are never added across sources.
    """
    total, unassigned = accumulator(), accumulator()
    days, products = defaultdict(accumulator), defaultdict(accumulator)
    preview_days = set()
    rows = db.scalars(
        select(WBDailyMetric)
        .where(
            *scope(WBDailyMetric, workspace_id, store_id),
            WBDailyMetric.source == Source.FINANCE,
            WBDailyMetric.dataset == str(run.id),
            WBDailyMetric.day.between(start, end),
            WBDailyMetric.currency == currency,
        )
        .execution_options(yield_per=500)
    )
    for row in rows:
        values = json.loads(
            vault.open(
                row.ciphertext,
                metric_context(
                    workspace_id,
                    store_id,
                    row.source,
                    row.dataset,
                    row.day,
                    row.nm_id,
                    row.currency,
                ),
            )
        )
        # Old previews are upgraded by the worker. Never guess absent accounting checks.
        if "profit_records" not in values or "profit_detail_v4_records" not in values:
            return None
        # A day touched by the import belongs to it, even if its records moved elsewhere.
        preview_days.add(row.day)
        if Decimal(values["profit_records"]) <= 0:
            continue
        product = unassigned if row.nm_id == "0" else products[row.nm_id]
        for field, value in values.items():
            if field.startswith("profit_"):
                for destination in (total, days[row.day], product):
                    destination[field.removeprefix("profit_")] += Decimal(value)
    if not total["records"]:
        # Nothing new for this period: the published report is complete on its own.
        return None
    if published is not None:
        for day, item in published_groups(db, vault, workspace_id, store_id, start, end, currency):
            if day in preview_days:
                continue
            product = unassigned if item["nm_id"] == "0" else products[item["nm_id"]]
            for destination in (total, days[day], product):
                # Costs wait for publication either way: partial_values hides cogs.
                for field, value in item["values"].items():
                    destination[field] += Decimal(value)
    add_expenses(db, vault, workspace_id, store_id, start, end, currency, total, days)

    def partial_values(values):
        rendered = render_values(values, False)
        # Matching returns to original sales and prices requires the published dataset.
        rendered.cogs = None
        rendered.financial_details["total_expenses"] = None
        rendered.financial_details["wb_expenses_total"] = None
        rendered.issues["import_in_progress"] = 1
        if values["sales"] or values["returns"]:
            rendered.issues["costs_pending"] = 1
        if not values["records"]:
            rendered.revenue = None
            rendered.for_pay = None
            for components in (
                rendered.wb_expenses,
                rendered.included_components,
                rendered.unreconciled_components,
            ):
                for field in components:
                    components[field] = None
        return rendered.model_dump()

    return ProfitReport(
        date_from=start,
        date_to=end,
        currency=currency,
        status="ready",
        is_partial=True,
        updated_at=run.preview_updated_at,
        period_covered=False,
        summary=ProfitValues(**partial_values(total)),
        unassigned=ProfitValues(**partial_values(unassigned)),
        daily=[
            ProfitDay(day=day, **partial_values(values)) for day, values in sorted(days.items())
        ],
        products=[
            ProfitProduct(nm_id=key, **partial_values(values))
            for key, values in sorted(products.items())
        ][offset : offset + limit],
        product_count=len(products),
        limit=limit,
        offset=offset,
    )


@money_precision()
def calculate(
    db, vault, workspace_id, store_id, start, end, currency, limit, offset, state, stale=False
):
    groups = published_groups(db, vault, workspace_id, store_id, start, end, currency)
    book = price_book(db, vault, workspace_id, store_id, {item["nm_id"] for _, item in groups})
    total, unassigned = accumulator(), accumulator()
    days, products = defaultdict(accumulator), defaultdict(accumulator)
    barcodes = defaultdict(set)
    missing_skus = set()
    for day, item in groups:
        if item["barcode"]:
            barcodes[item["nm_id"]].add(item["barcode"])
        cost = price_for(book, item, currency) if item["kind"] in {"sales", "returns"} else None
        product = unassigned if item["nm_id"] == "0" else products[item["nm_id"]]
        if cost is None and item["kind"] in {"sales", "returns"}:
            missing_skus.add((item["nm_id"], item["barcode"]))
        for destination in (total, days[day], product):
            add_group(destination, item["values"], cost)
    currency_available = (
        db.scalar(
            select(FinanceDay.day)
            .where(*scope(FinanceDay, workspace_id, store_id), FinanceDay.currency == currency)
            .limit(1)
        )
        is not None
    )
    if not currency_available:
        total["unavailable_report_currency"] = Decimal(1)
    add_expenses(db, vault, workspace_id, store_id, start, end, currency, total, days)
    complete = not stale and covered_period(db, workspace_id, store_id, start, end)
    product_rows = [
        ProfitProduct(
            nm_id=key,
            barcodes=sorted(barcodes[key]),
            **render_values(values, complete).model_dump(),
        )
        for key, values in sorted(products.items())
    ]
    summary = render_values(total, complete)
    if summary.records:
        summary.financial_details["missing_cost_skus"] = str(len(missing_skus))
    return ProfitReport(
        date_from=start,
        date_to=end,
        currency=currency,
        status="ready",
        updated_at=state.updated_at,
        is_partial=False,
        period_covered=complete,
        summary=summary,
        unassigned=render_values(unassigned, complete),
        daily=[
            ProfitDay(day=day, **render_values(values, complete).model_dump())
            for day, values in sorted(days.items())
        ],
        products=product_rows[offset : offset + limit],
        product_count=len(product_rows),
        limit=limit,
        offset=offset,
    )


def revision(db, workspace_id, store_id):
    state = db.get(FinanceProjection, (workspace_id, store_id), populate_existing=True)
    source = source_run(db, workspace_id, store_id)
    preview = db.scalar(
        select(SyncRun)
        .execution_options(populate_existing=True)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.FINANCE,
            SyncRun.status.in_(["queued", "running"]),
        )
        .limit(1)
    )
    costs = db.execute(
        select(func.count(), func.max(ProductCost.created_at)).where(
            *scope(ProductCost, workspace_id, store_id)
        )
    ).one()
    expenses = db.execute(
        select(
            func.count(), func.max(ExternalExpense.created_at), func.max(ExternalExpense.deleted_at)
        ).where(*scope(ExternalExpense, workspace_id, store_id))
    ).one()
    stamp = [
        str(source),
        str(state.source_run_id) if state else "",
        str(state.updated_at) if state else "",
        state.format_version if state else 0,
        *map(str, costs),
        *map(str, expenses),
        str(preview.id) if preview else "",
        preview.pages_processed if preview else 0,
        str(preview.preview_updated_at) if preview else "",
    ]

    def latest(*values):
        return max((value for value in values if value is not None), default=None)

    timestamps = {
        "published": latest(state.updated_at if state else None, costs[1], *expenses[1:]),
        "partial": latest(preview.preview_updated_at if preview else None, *expenses[1:]),
    }
    return state, source, preview, timestamps, json.dumps(stamp, separators=(",", ":"))


def calculate_snapshot(
    db, vault, workspace_id, store_id, start, end, currency, limit, offset, state, source, preview
):
    final_ready = bool(
        source
        and state
        and state.source_run_id == source
        and state.format_version in READABLE_FORMATS
    )
    # A projection of an earlier publication still holds every day it covered. Hiding it
    # while the next history chunk or refresh is running would drop whole months.
    published = state if state and state.format_version in READABLE_FORMATS else None
    if preview:
        partial = partial_report(
            db,
            vault,
            workspace_id,
            store_id,
            start,
            end,
            currency,
            limit,
            offset,
            preview,
            published=published,
        )
        if partial is not None:
            return partial
    if published:
        # Until the newest publication is projected, its days may be absent: never claim coverage.
        return calculate(
            db,
            vault,
            workspace_id,
            store_id,
            start,
            end,
            currency,
            limit,
            offset,
            state,
            stale=not final_ready,
        )
    return ProfitReport(
        date_from=start,
        date_to=end,
        currency=currency,
        status="preparing" if source or preview else "no_data",
        is_partial=False,
        limit=limit,
        offset=offset,
    )


# The cache key contains the data revision, so new or edited data always misses it and a
# longer lifetime cannot serve stale numbers. It decides how long an unused report
# survives; superseded revisions also stay until it ends, so it is bounded to keep Redis
# (shared with the task queue, maxmemory 192 MB) from filling with old versions.
CACHE_SECONDS = 3 * 3600


def report(db, redis, vault, workspace_id, store_id, start, end, currency, limit, offset):
    result = None
    for _ in range(3):
        state, source, preview, timestamps, stamp = revision(db, workspace_id, store_id)
        aad = f"perk-profit:v10:{workspace_id}:{store_id}:" + json.dumps(
            [stamp, str(start), str(end), currency, limit, offset]
        )
        key = "perk:profit:v10:" + vault.digest("profit-cache", aad)

        hit = False
        try:
            encrypted = redis.get(key)
            if isinstance(encrypted, (str, bytes)):
                result = ProfitReport.model_validate_json(
                    vault.open(
                        encrypted.decode() if isinstance(encrypted, bytes) else encrypted, aad
                    )
                )
                hit = True
            else:
                result = calculate_snapshot(
                    db,
                    vault,
                    workspace_id,
                    store_id,
                    start,
                    end,
                    currency,
                    limit,
                    offset,
                    state,
                    source,
                    preview,
                )
        except RedisError, InvalidTag, ValueError, KeyError:
            result = calculate_snapshot(
                db,
                vault,
                workspace_id,
                store_id,
                start,
                end,
                currency,
                limit,
                offset,
                state,
                source,
                preview,
            )
        *_, after = revision(db, workspace_id, store_id)
        if stamp != after:
            continue
        if result.status == "ready":
            result.updated_at = timestamps["partial" if result.is_partial else "published"]
        try:
            if hit:
                # Already stored under this revision: extend it instead of re-encrypting.
                redis.expire(key, CACHE_SECONDS)
            else:
                redis.set(key, vault.seal(result.model_dump_json(), aad), ex=CACHE_SECONDS)
        except RedisError:
            pass
        return result
    return ProfitReport(
        date_from=start,
        date_to=end,
        currency=currency,
        status="preparing",
        is_partial=False,
        limit=limit,
        offset=offset,
    )


@money_precision()
def abc(result, metric, limit, offset, a_threshold=Decimal(80), b_threshold=Decimal(95)):
    output = ProfitABC(
        date_from=result.date_from,
        date_to=result.date_to,
        currency=result.currency,
        metric=metric,
        status=result.status,
        limit=limit,
        offset=offset,
    )
    if result.status != "ready":
        return output
    if result.product_count != len(result.products):
        raise HTTPException(422, "Для ABC нужен полный набор товаров расчёта.")
    field = "revenue" if metric == "revenue" else "contribution_before_external_expenses"
    positives = []
    for item in result.products:
        value = getattr(item, field)
        if value is None:
            output.unknown_count += 1
        elif Decimal(value) < 0:
            output.negative_count += 1
        elif Decimal(value) == 0:
            output.zero_count += 1
        else:
            positives.append((item.nm_id, Decimal(value)))
    positives.sort(key=lambda item: (-item[1], item[0]))
    total = sum((value for _, value in positives), Decimal(0))
    output.positive_total, output.positive_count = format(total, "f"), len(positives)
    identities = {item.nm_id: item for item in result.products}
    cumulative, ranked = Decimal(0), []
    for nm_id, amount in positives:
        before = cumulative / total * 100
        cumulative += amount
        ranked.append(
            ABCItem(
                nm_id=nm_id,
                vendor_code=identities[nm_id].vendor_code,
                barcodes=identities[nm_id].barcodes,
                amount=format(amount, "f"),
                share_percent=format(amount / total * 100, ".4f"),
                cumulative_percent=format(cumulative / total * 100, ".4f"),
                group="A" if before < a_threshold else "B" if before < b_threshold else "C",
            )
        )
    output.items = ranked[offset : offset + limit]
    if (
        output.unknown_count
        or not result.period_covered
        or result.summary.issues.get("unavailable_report_currency")
    ):
        output.status = "incomplete"
    return output
