"""Ozon stock/price snapshot adapter. FBS is never merged across seller accounts."""

from datetime import timedelta
from decimal import Decimal

from app.modules.auth.dependencies import now
from app.modules.catalog import ozon_read
from app.modules.inventory import ozon_cover
from app.modules.inventory.overview_schemas import (
    FbsSizeStock,
    InventoryOverview,
    InventoryPosition,
)


def overview(
    db,
    vault,
    workspace_id,
    store,
    currency,
    can_cost,
    query="",
    only_stock=False,
    limit=0,
    offset=0,
    coverage_channel="fbo",
):
    from app.modules.inventory.overview import combine, valuation

    rows, stamp = ozon_read.snapshot(db, vault, workspace_id, store)
    state = ozon_read.state(db, workspace_id, store.id)
    cover = ozon_cover.read(db, vault, workspace_id, store.id)
    from app.modules.inventory.channel_cover import (
        channel_position,
        channel_total,
        ozon_channel_rates,
    )

    rates, channels_updated = ozon_channel_rates(db, vault, workspace_id, store.id)
    coverage_rows = []
    basis = {"fbo": "ozon_sales_28d_fbo", "fbs": "ozon_orders_28d_fbs", "all": "ozon_channels_28d"}[
        coverage_channel
    ]
    from app.modules.finance.variant_costs import apply, book
    from app.modules.sync.schemas import moscow_today

    prices_by_variant = (
        book(db, vault, workspace_id, store.id, currency, moscow_today()) if can_cost else {}
    )
    totals, positions = {"fbo": [], "fbs": []}, []
    for row in rows or []:
        if not ozon_read.matches(row, query):
            continue
        if only_stock and not any(row["channels"][key]["quantity"] > 0 for key in ("fbo", "fbs")):
            continue
        product = ozon_read.item(row, store, stamp, True)
        if can_cost:
            apply(product, prices_by_variant, moscow_today())
        variant = product.variants[0]
        prices = {variant.id: row["seller_price"]} if row["currency"] == currency else {}
        channels = {}
        for key in ("fbo", "fbs"):
            channels[key] = valuation(
                [{"chrt_id": variant.id, "quantity": row["channels"][key]["quantity"]}],
                True,
                prices,
                {variant.id: variant.unit_cost} if can_cost else {},
                can_cost,
                stamp,
            )
            totals[key].append(channels[key])
        skus = row.get("channel_skus", {}).get("fbo", [])
        cover_days, cover_status = ozon_cover.position(cover["products"], skus, cover["loading"])
        if coverage_channel != "fbo":
            fbo_facts = [
                cover["products"][sku] for sku in dict.fromkeys(skus) if sku in cover["products"]
            ]
            fbo_rate = (
                next((fact["ads"] for fact in fbo_facts), None) if len(fbo_facts) == 1 else None
            )
            fbs_skus = row.get("channel_skus", {}).get("fbs", [])
            fbs_rate = (
                sum(rates.get(sku, 0) for sku in set(fbs_skus))
                if rates is not None and fbs_skus
                else None
            )
            if channels["fbo"].units == 0:
                fbo_rate = 0
            if channels["fbs"].units == 0 and not fbs_skus:
                fbs_rate = Decimal(0)
            units = (
                channels["fbs"].units
                if coverage_channel == "fbs"
                else channels["fbo"].units + channels["fbs"].units
            )
            rate = (
                fbs_rate
                if coverage_channel == "fbs"
                else None
                if fbo_rate is None or fbs_rate is None
                else Decimal(fbo_rate) + fbs_rate
            )
            cover_days, cover_status = channel_position(units, rate)
            coverage_rows.append((units, rate))
        positions.append(
            InventoryPosition(
                product=product,
                coverage_channel=coverage_channel,
                turnover_basis=basis,
                turnover_days=cover_days,
                turnover_status=cover_status,
                **channels,
                fbs_sizes=[
                    FbsSizeStock(
                        variant_id=variant.id,
                        quantity=row["channels"]["fbs"]["quantity"],
                        warehouses={},
                    )
                ],
            )
        )
    if not positions:
        for key in totals:
            totals[key].append(valuation([], rows is not None, {}, {}, can_cost, stamp))
    fbo, fbs = [combine(totals[key], can_cost) for key in ("fbo", "fbs")]
    required = []
    for row in rows or []:
        if row["channels"]["fbo"]["quantity"] > 0:
            aliases = row.get("channel_skus", {}).get("fbo", [])
            required.append(
                next(
                    (sku for sku in aliases if sku in cover["products"]),
                    "missing:" + row["external_id"],
                )
            )
    total_cover, cover_partial = ozon_cover.portfolio(cover["products"], required)
    if coverage_channel != "fbo":
        total_cover, cover_partial = channel_total(coverage_rows)
    return InventoryOverview(
        coverage_channel=coverage_channel,
        fbo=fbo,
        fbs=fbs,
        total=combine([fbo, fbs], can_cost),
        items=positions[offset : offset + limit],
        count=len(positions),
        limit=limit,
        offset=offset,
        currency=currency,
        can_cost=can_cost,
        is_loading=state["status"] in {"pending", "queued", "running"},
        missing_sources=["ozon_catalog"] if rows is None else [],
        error_code=state["error_code"],
        turnover_supported=True,
        turnover_basis=basis,
        turnover_days=total_cover,
        turnover_updated_at=cover["updated_at"],
        turnover_loading=cover["loading"],
        turnover_partial=cover_partial,
        turnover_stale=bool(
            cover["updated_at"] and now() - cover["updated_at"] > timedelta(hours=12)
        ),
        other_channels=sorted(
            {
                key
                for row in rows or []
                for key, value in row["channels"].items()
                if key not in {"fbo", "fbs"} and value["quantity"]
            }
        ),
    )
