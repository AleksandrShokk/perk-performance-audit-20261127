"""Stable source listing IDs, without guessing a cross-market product match."""

from uuid import NAMESPACE_URL, uuid5


def product_key(store_id, marketplace, external_id):
    return str(uuid5(NAMESPACE_URL, f"perk:{store_id}:{marketplace}:{external_id}"))


def variant_key(product_id, external_id):
    return str(uuid5(NAMESPACE_URL, f"{product_id}:variant:{external_id}"))
