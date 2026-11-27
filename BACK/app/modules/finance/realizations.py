"""Tenant-bound hashed posting lookup. Analytic access exposes buyer prices only."""

import json
from collections import defaultdict

from sqlalchemy import select

from app.modules.finance.marketplace_models import MarketplaceRealization


def posting_key(vault, workspace_id, store_id, number):
    return vault.digest(f"ozon-posting:{workspace_id}:{store_id}", number)


def aad(workspace_id, store_id, day, key, sku):
    return f"perk-realization:v1:{workspace_id}:{store_id}:{day}:{key}:{sku}"


def prices(db, vault, workspace_id, store_id, keys):
    candidates = defaultdict(set)
    keys = sorted(set(keys))
    for offset in range(0, len(keys), 1000):
        rows = db.scalars(
            select(MarketplaceRealization).where(
                MarketplaceRealization.workspace_id == workspace_id,
                MarketplaceRealization.store_id == store_id,
                MarketplaceRealization.posting_key.in_(keys[offset : offset + 1000]),
            )
        )
        for row in rows:
            value = json.loads(
                vault.open(
                    row.ciphertext, aad(workspace_id, store_id, row.day, row.posting_key, row.sku)
                )
            )
            candidates[(row.posting_key, row.sku)].add((value["price"], value["currency"]))
    # Multiple actual prices within one SKU/posting cannot safely be averaged for an order.
    return {
        key: {"price": next(iter(values))[0], "currency": next(iter(values))[1]}
        for key, values in candidates.items()
        if len(values) == 1 and next(iter(values))[0] is not None
    }
