"""Neutral product labels for analytics, without stock, prices or costs."""

import json
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.integrations.wildberries.data import Source
from app.modules.catalog.marketplace_models import MarketplaceCatalogSnapshot
from app.modules.catalog.ozon_jobs import aad
from app.modules.sync.models import WBRecord
from app.modules.sync.read import retained
from app.modules.sync.service import context

logger = logging.getLogger(__name__)
# Funnel record keys start with the ISO day ("2026-11-20:<nm_id>:..."), so a day range is a
# primary-key range scan. Without it the lookup read every funnel record of the store
# (seconds, growing with history, and close to the 5 s statement timeout).
LOOKUP_DAYS = 31


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


def enrich(products, db, vault, workspace_id, store_id, marketplace, start=None, end=None):
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
            for key, ciphertext in funnel_labels(db, workspace_id, store_id, missing, start, end):
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


def funnel_labels(db, workspace_id, store_id, missing, start, end):
    """Latest funnel record of each missing article within the report's last days.

    Labels are optional: a slow or failed lookup leaves them empty instead of failing
    the report (the statement runs in a savepoint).
    """
    article = func.split_part(WBRecord.record_key, ":", 2)
    conditions = [
        WBRecord.workspace_id == workspace_id,
        WBRecord.store_id == store_id,
        WBRecord.source == Source.FUNNEL,
        article.in_(missing),
    ]
    if end is not None:
        first = end - timedelta(days=LOOKUP_DAYS - 1)
        if start is not None:
            first = max(start, first)
        conditions += [
            WBRecord.record_key >= f"{first.isoformat()}:",
            WBRecord.record_key < f"{(end + timedelta(days=1)).isoformat()}:",
        ]
    try:
        with db.begin_nested():
            return list(
                db.execute(
                    select(WBRecord.record_key, WBRecord.ciphertext)
                    .where(*conditions)
                    .distinct(article)
                    .order_by(article, WBRecord.updated_at.desc())
                )
            )
    except DBAPIError:
        logger.warning("funnel_labels_unavailable")
        return []
