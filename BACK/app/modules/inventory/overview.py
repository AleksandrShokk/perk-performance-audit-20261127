"""One stock read model for the dashboard and the paginated inventory list.

Current seller prices after seller discount, without WB discount. Unknown is never zero.
Stock coverage uses WB stock history and orders over 28 complete Moscow days.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.catalog.schemas import ProductItem, ProductVariant, WarehouseStock
from app.modules.catalog.service import matches, products
from app.modules.inventory.overview_schemas import (
    FbsSizeStock,
    InventoryAmounts,
    InventoryOverview,
    InventoryPosition,
)
from app.modules.inventory.stock_cover import WINDOW, coverage_summary, product_coverage
from app.modules.sync.read import read_once, retained, source_states


def amount(value):
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def valuation(rows, known, prices, costs, can_cost, updated_at=None):
    units, retail, cost, missing_price, missing_cost = 0, Decimal(0), Decimal(0), False, False
    priced, costed = False, False
    with localcontext() as ctx:
        ctx.prec = 64
        for row in rows:
            quantity = row["quantity"]
            units += quantity
            if not quantity:
                continue
            key = row["chrt_id"]
            price = prices.get(key)
            unit_cost = costs.get(key)
            missing_price |= price is None
            missing_cost |= unit_cost is None
            if price is not None:
                retail += Decimal(price) * quantity
                priced = True
            if unit_cost is not None:
                cost += Decimal(unit_cost) * quantity
                costed = True
        return InventoryAmounts(
            units=units if known else None,
            retail_value=amount(retail) if known and (priced or not units) else None,
            retail_complete=known and not missing_price,
            cost_value=amount(cost) if can_cost and known and (costed or not units) else None,
            cost_complete=can_cost and known and not missing_cost,
            updated_at=updated_at,
            stale=bool(updated_at and now() - updated_at > timedelta(days=2)),
        )


def combine(values, can_cost):
    def total(field):
        # Empty, confirmed positions do not make unknown priced stock worth zero.
        amounts = [getattr(row, field) for row in values if row.units != 0]
        if values and all(row.units == 0 for row in values):
            return "0.00"
        with localcontext() as ctx:
            ctx.prec = 64
            return (
                amount(sum((Decimal(value) for value in amounts if value is not None), Decimal(0)))
                if any(value is not None for value in amounts)
                else None
            )

    dates = [row.updated_at for row in values if row.updated_at]
    return InventoryAmounts(
        units=sum(row.units for row in values)
        if values and all(row.units is not None for row in values)
        else None,
        retail_value=total("retail_value"),
        retail_complete=bool(values) and all(row.retail_complete for row in values),
        cost_value=total("cost_value") if can_cost else None,
        cost_complete=can_cost and bool(values) and all(row.cost_complete for row in values),
        updated_at=min(dates) if dates else None,
        stale=any(row.stale for row in values),
    )


def wb_overview(
    db,
    vault,
    workspace_id,
    stores,
    currency,
    can_cost,
    query="",
    only_stock=False,
    limit=0,
    offset=0,
    coverage_channel="fbo",
):
    # The catalog part reads stocks too: decrypt each snapshot once per call.
    with read_once(db):
        return build_wb_overview(
            db,
            vault,
            workspace_id,
            stores,
            currency,
            can_cost,
            query,
            only_stock,
            limit,
            offset,
            coverage_channel,
        )


def build_wb_overview(
    db,
    vault,
    workspace_id,
    stores,
    currency,
    can_cost,
    query,
    only_stock,
    limit,
    offset,
    coverage_channel,
):
    # Positions are assembled only for the requested page: totals need every SKU, but a
    # dashboard page shows 10-20 of ~1000 (each with variants and warehouses).
    pending, channel_totals = [], {"fbo": [], "fbs": []}
    history_source = {
        "fbo": Source.SUPPLY_DEMAND,
        "fbs": Source.SUPPLY_DEMAND_FBS,
        "all": Source.STOCK_HISTORY,
    }[coverage_channel]
    loading, missing, report_rows, reports_complete = False, set(), [], bool(stores)
    report_dates = []
    report_loading = False
    position_count = 0
    for store in stores:
        catalog = products(
            db, vault, workspace_id, [store], currency, "", False, False, True, can_cost, None, 0
        )
        by_article = {row.nm_id: row for row in catalog.items}
        states = source_states(
            db,
            workspace_id,
            store.id,
            [Source.CATALOG, Source.STOCKS, Source.FBS, Source.PRICES, history_source],
        )
        loading |= any(state.loading for state in states.values())
        successful = {source: state.success for source, state in states.items()}
        missing.update(str(source) for source, run in successful.items() if run is None)
        prices = (
            {
                row["nm_id"]: row
                for row in retained(db, vault, workspace_id, store.id, Source.PRICES)
            }
            if successful[Source.PRICES]
            else {}
        )
        stocks = {"fbo": defaultdict(list), "fbs": defaultdict(list)}
        for channel, source in (("fbo", Source.STOCKS), ("fbs", Source.FBS)):
            if successful[source]:
                for row in retained(db, vault, workspace_id, store.id, source):
                    stocks[channel][row["nm_id"]].append(row)
        history_run = successful[history_source]
        history_rows = {}
        history_loading = states[history_source].loading
        report_loading |= history_loading
        if history_run and history_run.date_from and history_run.date_to:
            history_rows = {
                row["nm_id"]: row
                for row in retained(db, vault, workspace_id, store.id, history_source)
                if row["date_from"] == history_run.date_from.isoformat()
                and row["date_to"] == history_run.date_to.isoformat()
            }
            report_dates.append(history_run.finished_at)
        reports_complete &= bool(history_run and history_run.date_from and history_run.date_to)
        report_rows.extend(history_rows.values())
        for article in sorted(set(by_article) | set(stocks["fbo"]) | set(stocks["fbs"])):
            product = by_article.get(article) or ProductItem(
                store_id=store.id,
                store_name=store.name,
                nm_id=article,
                vendor_code="",
                title=f"Товар {article}",
                brand="",
                subject="",
                colors=[],
                variants=[],
                stock=None,
                stock_updated_at=None,
                stock_stale=False,
                missing_cost_variants=None,
            )
            if query and not matches(
                {**product.model_dump(), "sizes": [row.model_dump() for row in product.variants]},
                query,
            ):
                continue
            variants = {row.chrt_id: row for row in product.variants}
            for row in stocks["fbo"][article] + stocks["fbs"][article]:
                if row["chrt_id"] not in variants:
                    variants[row["chrt_id"]] = ProductVariant(
                        chrt_id=row["chrt_id"],
                        size="",
                        barcodes=[],
                        stock=None,
                        to_client=None,
                        from_client=None,
                        warehouses=[],
                        unit_cost=None,
                    )
            price_row = prices.get(article, {})
            current_prices = (
                price_row.get("prices", {}) if price_row.get("currency") == currency else {}
            )
            costs = {key: row.unit_cost for key, row in variants.items()} if can_cost else {}
            metrics = {}
            for channel, source in (("fbo", Source.STOCKS), ("fbs", Source.FBS)):
                run = successful[source]
                metrics[channel] = valuation(
                    stocks[channel][article],
                    bool(run),
                    current_prices,
                    costs,
                    can_cost,
                    min(run.finished_at, successful[Source.PRICES].finished_at)
                    if run
                    and successful[Source.PRICES]
                    and any(row["quantity"] for row in stocks[channel][article])
                    else run.finished_at
                    if run
                    else None,
                )
            if only_stock and not any((value.units or 0) > 0 for value in metrics.values()):
                continue
            for channel in metrics:
                channel_totals[channel].append(metrics[channel])
            position_count += 1
            if not limit:
                continue
            pending.append(
                (
                    (product.vendor_code.casefold(), product.nm_id, str(product.store_id)),
                    product,
                    variants,
                    metrics,
                    stocks["fbo"][article],
                    stocks["fbs"][article],
                    bool(successful[Source.STOCKS]),
                    history_rows.get(article),
                    history_loading,
                )
            )
        # Empty confirmed catalogs still have a known zero balance.
        if not by_article and not any(stocks.values()):
            for channel, source in (("fbo", Source.STOCKS), ("fbs", Source.FBS)):
                channel_totals[channel].append(
                    valuation([], bool(successful[source]), {}, {}, can_cost)
                )
    fbo, fbs = [combine(channel_totals[channel], can_cost) for channel in ("fbo", "fbs")]
    pending.sort(key=lambda row: row[0])
    positions = [position(coverage_channel, *row[1:]) for row in pending[offset : offset + limit]]
    cover, partial = coverage_summary(report_rows) if reports_complete else (None, False)
    return InventoryOverview(
        coverage_channel=coverage_channel,
        fbo=fbo,
        fbs=fbs,
        total=combine([fbo, fbs], can_cost),
        turnover_days=cover,
        turnover_partial=partial,
        turnover_updated_at=min(report_dates) if report_dates else None,
        turnover_loading=report_loading,
        turnover_stale=any(now() - value > timedelta(days=2) for value in report_dates),
        observed_days=WINDOW if reports_complete else 0,
        items=positions,
        count=position_count,
        limit=limit,
        offset=offset,
        currency=currency,
        can_cost=can_cost,
        is_loading=loading,
        missing_sources=sorted(missing),
    )


def position(
    coverage_channel,
    product,
    variants,
    metrics,
    fbo_stock,
    fbs_stock,
    stocks_known,
    history_row,
    history_loading,
):
    variants = dict(variants)
    for chrt, variant in list(variants.items()):
        fbo_rows = [row for row in fbo_stock if row["chrt_id"] == chrt]
        warehouses = defaultdict(int)
        for row in fbo_rows:
            warehouses[row["warehouse_name"]] += row["quantity"]
        variants[chrt] = variant.model_copy(
            update={
                "stock": sum(row["quantity"] for row in fbo_rows) if stocks_known else None,
                "warehouses": [
                    WarehouseStock(name=name, quantity=quantity)
                    for name, quantity in warehouses.items()
                ],
            }
        )
    product = ProductItem.model_validate(
        {**product.model_dump(), "variants": list(variants.values())}
    )
    fbs_sizes = defaultdict(lambda: {"quantity": 0, "warehouses": defaultdict(int)})
    for row in fbs_stock:
        target = fbs_sizes[row["chrt_id"]]
        target["quantity"] += row["quantity"]
        target["warehouses"][row["warehouse_name"]] += row["quantity"]
    cover_days, cover_status = product_coverage(history_row, loading=history_loading)
    return InventoryPosition(
        product=product,
        coverage_channel=coverage_channel,
        **metrics,
        fbs_sizes=[FbsSizeStock(chrt_id=key, **value) for key, value in fbs_sizes.items()],
        turnover_days=cover_days,
        turnover_status=cover_status,
    )


def overview(
    db,
    vault,
    workspace_id,
    stores,
    currency,
    can_cost,
    query="",
    only_stock=False,
    limit=0,
    offset=0,
    coverage_channel="fbo",
):
    if all(store.marketplace == "wildberries" for store in stores):
        return wb_overview(
            db,
            vault,
            workspace_id,
            stores,
            currency,
            can_cost,
            query,
            only_stock,
            limit,
            offset,
            coverage_channel,
        )
    from app.modules.inventory.ozon_overview import overview as ozon_overview

    reports = []
    for store in stores:
        reader = ozon_overview if store.marketplace == "ozon" else wb_overview
        report = reader(
            db,
            vault,
            workspace_id,
            [store] if reader is wb_overview else store,
            currency,
            can_cost,
            query,
            only_stock,
            50000 if limit else 0,
            0,
            coverage_channel,
        )
        reports.append(report)
    items = [item for report in reports for item in report.items]
    items.sort(key=lambda item: (item.product.vendor_code.casefold(), item.product.id))
    fbo = combine([report.fbo for report in reports], can_cost)
    # Different accounts can publish the same physical seller stock. No inferred deduplication.
    mixed = len(stores) > 1
    from app.modules.inventory.settings import fbs_mode

    separate = mixed and fbs_mode(db, workspace_id) == "separate"
    fbs = (
        combine([report.fbs for report in reports], can_cost)
        if separate
        else InventoryAmounts()
        if mixed
        else reports[0].fbs
    )
    return InventoryOverview(
        coverage_channel=coverage_channel,
        fbo=fbo,
        fbs=fbs,
        total=combine([fbo, fbs], can_cost)
        if separate
        else InventoryAmounts()
        if mixed
        else reports[0].total,
        items=items[offset : offset + limit],
        count=sum(report.count for report in reports),
        limit=limit,
        offset=offset,
        currency=currency,
        can_cost=can_cost,
        is_loading=any(report.is_loading for report in reports),
        missing_sources=sorted({source for report in reports for source in report.missing_sources}),
        aggregation_status="warehouse_mapping_required" if mixed and not separate else "ready",
        error_code=next((report.error_code for report in reports if report.error_code), None),
        turnover_supported=not mixed and all(report.turnover_supported for report in reports),
        turnover_basis="mixed" if mixed else reports[0].turnover_basis,
        turnover_days=reports[0].turnover_days if not mixed else None,
        turnover_updated_at=reports[0].turnover_updated_at if not mixed else None,
        turnover_loading=any(report.turnover_loading for report in reports),
        turnover_partial=any(report.turnover_partial for report in reports),
        turnover_stale=any(report.turnover_stale for report in reports),
        other_channels=sorted({channel for report in reports for channel in report.other_channels}),
    )
