"""Neutral product labels for analytics, without stock, prices or costs."""

import json

from sqlalchemy import func, select

from app.integrations.wildberries.data import Source
from app.modules.catalog.marketplace_models import MarketplaceCatalogSnapshot
from app.modules.catalog.ozon_jobs import aad
from app.modules.sync.models import WBRecord
from app.modules.sync.read import retained
from app.modules.sync.service import context


def labels(rows, marketplace):
    result, ambiguous = {}, set()
    for row in rows:
        codes = (
            {str(row["nm_id"])}
            if marketplace == "wildberries"
            else {
                str(code)
                for code in [
                    row.get("marketplace_code"),
                    *row.get("sku_aliases", []),
                    *(sku for values in row.get("channel_skus", {}).values() for sku in values),
                ]
                if code
            }
        )
        barcodes = (
            [code for size in row.get("sizes", []) for code in size.get("barcodes", [])]
            if marketplace == "wildberries"
            else row.get("barcodes", [])
        )
        value = {
            "title": row.get("title", ""),
            "vendor_code": row.get("vendor_code", ""),
            "photos": row.get("photos", []),
            "barcodes": list(dict.fromkeys(barcodes)),
        }
        for code in codes:
            if code in result:
                ambiguous.add(code)
            else:
                result[code] = value
    return {code: value for code, value in result.items() if code not in ambiguous}


def enrich(products, db, vault, workspace_id, store_id, marketplace):
    if not products:
        return products
    if marketplace == "ozon":
        row = db.get(MarketplaceCatalogSnapshot, (workspace_id, store_id))
        rows = json.loads(vault.open(row.ciphertext, aad(workspace_id, store_id))) if row else []
    else:
        rows = retained(db, vault, workspace_id, store_id, Source.CATALOG)
    metadata = labels(rows, marketplace)
    if marketplace == "wildberries":
        missing = {
            str(product["nm_id"])
            for product in products
            if not metadata.get(str(product["nm_id"]), {}).get("vendor_code")
        }
        if missing:
            article = func.split_part(WBRecord.record_key, ":", 2)
            records = db.execute(
                select(WBRecord.record_key, WBRecord.ciphertext)
                .where(
                    WBRecord.workspace_id == workspace_id,
                    WBRecord.store_id == store_id,
                    WBRecord.source == Source.FUNNEL,
                    article.in_(missing),
                )
                .distinct(article)
                .order_by(article, WBRecord.updated_at.desc())
            )
            for key, ciphertext in records:
                row = json.loads(
                    vault.open(ciphertext, context(workspace_id, store_id, Source.FUNNEL, key))
                )
                code = str(row.get("nm_id", ""))
                vendor = row.get("vendor_code")
                if vendor:
                    metadata.setdefault(code, {})["vendor_code"] = vendor
    # Match only native IDs inside this store. Never join by article, title or another store.
    return [
        {
            **product,
            **metadata.get(
                str(product.get("marketplace_code") if marketplace == "ozon" else product["nm_id"]),
                {},
            ),
        }
        for product in products
    ]
