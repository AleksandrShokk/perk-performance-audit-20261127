"""Use Ozon's native FBO idc/ads facts; never average days or duplicate global ads."""

import json
from collections import defaultdict
from decimal import Decimal, localcontext

from app.modules.insights.marketplace_models import MarketplaceStockCover, OzonAnalyticsSync
from app.modules.insights.ozon_sales import integer, number
from app.modules.supplies.destinations.normalize import ozon_clusters


def aad(workspace_id, store_id):
    return f"perk-stock-cover:v1:{workspace_id}:{store_id}:ozon"


def normalize(rows):
    products = defaultdict(lambda: {"ads": set(), "idc": set(), "grades": set(), "warehouses": {}})
    for row in rows:
        sku = str(integer(row["sku"], positive=True))
        key = (
            str(row["warehouse_id"]),
            str(row.get("cluster_id", "")),
            str(row.get("placement_zone", "")),
        )
        available = integer(row["available_stock_count"])
        product = products[sku]
        if key in product["warehouses"]:
            if product["warehouses"][key] != available:
                raise ValueError("conflicting_warehouse")
            continue
        product["warehouses"][key] = available
        ads, idc = number(row.get("ads")), number(row.get("idc"))
        product["ads"].add(format(ads.normalize(), "f") if ads is not None else None)
        if idc is not None:
            product["idc"].add(format(idc.normalize(), "f"))
        product["grades"].add(row.get("turnover_grade"))
    clusters = ozon_clusters(rows)
    return {
        sku: {
            "destinations": clusters.get(sku, []),
            "available": sum(product["warehouses"].values()),
            "ads": next(iter(product["ads"])) if len(product["ads"]) == 1 else None,
            "days": next(iter(product["idc"])) if len(product["idc"]) == 1 else None,
            "no_sales": product["grades"] <= {"NO_SALES", "RESTRICTED_NO_SALES", "WAS_NO_SALES"},
        }
        for sku, product in products.items()
    }


def read(db, vault, workspace_id, store_id):
    row = db.get(MarketplaceStockCover, (workspace_id, store_id))
    job = db.get(OzonAnalyticsSync, (workspace_id, store_id, "stock_cover"))
    return {
        "products": json.loads(vault.open(row.ciphertext, aad(workspace_id, store_id)))
        if row
        else {},
        "updated_at": row.updated_at if row else None,
        "loading": bool(job and job.status in {"pending", "queued", "running"}),
        "error_code": job.error_code if job else None,
    }


def position(rows, skus, loading=False):
    facts = [rows[sku] for sku in dict.fromkeys(skus) if sku in rows]
    if not facts:
        return None, "loading" if loading else "no_data"
    if len(facts) == 1:
        row = facts[0]
        if row["no_sales"] and row["ads"] is not None and Decimal(row["ads"]) == 0:
            return None, "no_sales"
        return (row["days"], "ready") if row["days"] is not None else (None, "no_data")
    days, partial = portfolio({str(index): row for index, row in enumerate(facts)}, [])
    return days, "ready" if days is not None and not partial else "no_data"


def portfolio(products, required_skus):
    """Stock / demand for available positions. Unknown positions mark a partial result.

    Sold-out SKUs cannot consume unrelated inventory. Global ads is used once per SKU.
    """
    partial = any(sku not in products for sku in required_skus)
    stock, demand, sold_out = 0, Decimal(0), False
    with localcontext() as context:
        context.prec = 64
        for row in products.values():
            if row["available"] == 0:
                sold_out |= row["ads"] is not None and Decimal(row["ads"]) > 0
                continue
            if row["ads"] is None:
                partial = True
                continue
            stock += row["available"]
            demand += Decimal(row["ads"])
        if demand <= 0:
            return ("0.00" if stock == 0 and sold_out else None), partial
        return format((Decimal(stock) / demand).quantize(Decimal("0.01")), "f"), partial
