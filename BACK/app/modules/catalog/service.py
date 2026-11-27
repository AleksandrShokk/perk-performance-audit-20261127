"""Read the retained catalog, stock and price history; never call WB on a page request."""

from collections import defaultdict
from datetime import timedelta

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.catalog.schemas import (
    ProductItem,
    ProductPage,
    ProductVariant,
    WarehouseStock,
)
from app.modules.finance.report import price_book, price_for
from app.modules.sync.read import retained, source_states
from app.modules.sync.schemas import moscow_today


def matches(product, query):
    words = query.casefold().split()
    text = " ".join(
        [
            product.get("title", ""),
            product.get("vendor_code", ""),
            product["nm_id"],
            product.get("brand", ""),
            *product.get("colors", []),
            *(code for size in product.get("sizes", []) for code in size["barcodes"]),
        ]
    ).casefold()
    return all(word in text for word in words)


def variant_price(book, article, barcodes, currency, at):
    explicit = {
        price_for(book, {"nm_id": article, "barcode": code, "cost_day": at}, currency)
        for code in barcodes
        if any(str(day) <= at for day, _ in book.get((article, code, currency), []))
    }
    if explicit:
        return format(explicit.pop(), "f") if len(explicit) == 1 and None not in explicit else None
    price = price_for(
        book,
        {"nm_id": article, "barcode": next(iter(barcodes), ""), "cost_day": at},
        currency,
    )
    return format(price, "f") if price is not None else None


def wb_products(
    db,
    vault,
    workspace_id,
    stores,
    currency,
    query,
    only_stock,
    missing_cost,
    can_stock,
    can_cost,
    limit,
    offset,
    identities=None,
):
    items, loading, partial = [], False, False
    at = moscow_today().isoformat()
    for store in stores:
        states = source_states(db, workspace_id, store.id, [Source.CATALOG, Source.STOCKS])
        loading |= any(state.loading for state in states.values())
        stock_run = states[Source.STOCKS].success
        catalog_ready = states[Source.CATALOG].success is not None
        partial |= not catalog_ready or (can_stock and stock_run is None)
        cards = [
            row
            for row in retained(db, vault, workspace_id, store.id, Source.CATALOG)
            if matches(row, query)
        ]
        if identities is not None:
            identities.update({(str(store.id), row["nm_id"]): row for row in cards})
        articles = {row["nm_id"] for row in cards}
        stocks = defaultdict(list)
        stock_sizes = defaultdict(set)
        if can_stock and stock_run is not None:
            for row in retained(db, vault, workspace_id, store.id, Source.STOCKS):
                if row["nm_id"] in articles:
                    stocks[(row["nm_id"], row["chrt_id"])].append(row)
                    stock_sizes[row["nm_id"]].add(row["chrt_id"])
        book = price_book(db, vault, workspace_id, store.id, articles) if can_cost else None
        for card in cards:
            variants = []
            sizes = {size["chrt_id"]: size for size in card.get("sizes", [])}
            # Do not lose stock of a size temporarily missing from the latest catalog.
            for chrt in sorted(stock_sizes[card["nm_id"]]):
                if chrt not in sizes:
                    sizes[chrt] = {"chrt_id": chrt, "size": "", "barcodes": []}
            for size in sizes.values():
                rows = stocks[(card["nm_id"], size["chrt_id"])]
                known = can_stock and stock_run is not None
                warehouses = defaultdict(int)
                for row in rows:
                    warehouses[row["warehouse_name"]] += row["quantity"]
                variants.append(
                    ProductVariant(
                        **size,
                        stock=sum(row["quantity"] for row in rows) if known else None,
                        to_client=sum(row["in_way_to_client"] for row in rows) if known else None,
                        from_client=sum(row["in_way_from_client"] for row in rows)
                        if known
                        else None,
                        warehouses=[
                            WarehouseStock(name=name, quantity=quantity)
                            for name, quantity in sorted(warehouses.items())
                        ],
                        unit_cost=variant_price(book, card["nm_id"], size["barcodes"], currency, at)
                        if can_cost
                        else None,
                    )
                )
            stock = (
                sum(row.stock for row in variants) if can_stock and stock_run is not None else None
            )
            missing = sum(row.unit_cost is None for row in variants) if can_cost else None
            if only_stock and not stock:
                continue
            if missing_cost and not missing:
                continue
            items.append(
                ProductItem(
                    store_id=store.id,
                    store_name=store.name,
                    **{
                        key: card.get(key, "")
                        for key in ("nm_id", "vendor_code", "title", "brand", "subject")
                    },
                    colors=card.get("colors", []),
                    photos=card.get("photos", []),
                    marketplace=card.get("marketplace", store.marketplace),
                    variants=variants,
                    stock=stock,
                    stock_updated_at=stock_run.finished_at if can_stock and stock_run else None,
                    stock_stale=bool(
                        can_stock
                        and stock_run
                        and now() - stock_run.finished_at > timedelta(days=2)
                    ),
                    missing_cost_variants=missing,
                )
            )
    items.sort(key=lambda row: (row.vendor_code.casefold(), row.nm_id, str(row.store_id)))
    return ProductPage(
        items=items[offset : offset + limit] if limit is not None else items[offset:],
        total=len(items),
        total_variants=sum(len(row.variants) for row in items),
        missing_cost_variants=sum(row.missing_cost_variants for row in items) if can_cost else None,
        stock_units=sum(row.stock for row in items)
        if items and all(row.stock is not None for row in items)
        else None,
        currency=currency,
        limit=limit if limit is not None else len(items),
        offset=offset,
        is_loading=loading,
        is_partial=partial,
    )


def products(
    db,
    vault,
    workspace_id,
    stores,
    currency,
    query,
    only_stock,
    missing_cost,
    can_stock,
    can_cost,
    limit,
    offset,
    identities=None,
):
    if all(store.marketplace == "wildberries" for store in stores):
        return wb_products(
            db,
            vault,
            workspace_id,
            stores,
            currency,
            query,
            only_stock,
            missing_cost,
            can_stock,
            can_cost,
            limit,
            offset,
            identities,
        )
    from app.modules.catalog import ozon_read

    page = wb_products(
        db,
        vault,
        workspace_id,
        [store for store in stores if store.marketplace == "wildberries"],
        currency,
        query,
        only_stock,
        missing_cost,
        can_stock,
        can_cost,
        None,
        0,
        identities,
    )
    items = list(page.items)
    loading, partial = page.is_loading, page.is_partial
    error_code = None
    for store in stores:
        if store.marketplace != "ozon":
            continue
        extra, active, incomplete, problem = ozon_read.products(
            db,
            vault,
            workspace_id,
            store,
            query,
            only_stock,
            missing_cost,
            can_stock,
            can_cost,
            currency,
        )
        items.extend(extra)
        loading |= active
        partial |= incomplete
        error_code = error_code or problem
    items.sort(key=lambda row: (row.vendor_code.casefold(), str(row.store_id), row.id))
    return ProductPage(
        error_code=error_code,
        items=items[offset : offset + limit] if limit is not None else items[offset:],
        total=len(items),
        total_variants=sum(len(row.variants) for row in items),
        missing_cost_variants=sum(row.missing_cost_variants or 0 for row in items)
        if can_cost
        else None,
        stock_units=None
        if len(stores) > 1
        else sum(row.stock for row in items)
        if items and all(row.stock is not None for row in items)
        else None,
        currency=currency,
        limit=limit if limit is not None else len(items),
        offset=offset,
        is_loading=loading,
        is_partial=partial,
    )
