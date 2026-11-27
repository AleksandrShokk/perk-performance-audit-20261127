"""Normalize marketplace facts only. No inference from titles or vendor codes."""

from decimal import Decimal
from urllib.parse import urlsplit

from app.integrations.ozon.catalog_client import ImportError


def identifier(value):
    text = str(value)
    if not text.isdecimal() or int(text) <= 0 or len(text) > 32:
        raise ValueError("identifier")
    return text


def photos(values):
    # Render URLs supplied by Ozon; never fetch them on the backend.
    return list(
        dict.fromkeys(
            url
            for url in values
            if isinstance(url, str) and urlsplit(url).scheme == "https" and urlsplit(url).netloc
        )
    )[:50]


def normalize(info, attributes, stocks, prices, definitions):
    pid = identifier(info["id"])
    if any(
        str(row.get("id", row.get("product_id"))) != pid for row in (attributes, stocks, prices)
    ):
        raise ValueError("product_identity")
    values = {}
    for row in attributes.get("attributes", []):
        name = definitions.get(str(row["id"]), "").strip().casefold()
        values[name] = [
            value["value"].strip()
            for value in row["values"]
            if isinstance(value.get("value"), str) and value["value"].strip()
        ]
    size = next(
        (
            values[name]
            for name in ("российский размер", "размер производителя", "размер", "размер (рус)")
            if values.get(name)
        ),
        [],
    )
    channels, channel_skus = {}, {}
    for row in stocks["stocks"]:
        channel = row["type"].lower()
        sku = row.get("sku")
        if isinstance(sku, int) and not isinstance(sku, bool) and sku > 0:
            channel_skus.setdefault(channel, set()).add(str(sku))
        present, reserved = row["present"], row["reserved"]
        if (
            not isinstance(present, int)
            or isinstance(present, bool)
            or present < 0
            or not isinstance(reserved, int)
            or reserved < 0
        ):
            raise ValueError("stock")
        # Preserve provider values independently: never add reserved to present.
        target = channels.setdefault(channel, {"quantity": 0, "reserved": 0})
        target["quantity"] += present
        target["reserved"] += reserved
    # A successful complete per-product stock response establishes an absent channel at zero.
    for channel in ("fbo", "fbs"):
        channels.setdefault(channel, {"quantity": 0, "reserved": 0})
    price = prices.get("price", {})
    raw_price = price.get("marketing_seller_price")
    seller_price = None
    if raw_price not in (None, ""):
        value = Decimal(str(raw_price))
        if not value.is_finite() or value < 0:
            raise ValueError("price")
        seller_price = format(value, "f")
    group = (info.get("model_info") or {}).get("model_id")
    group = identifier(group) if group else None
    if not isinstance(info.get("name"), str) or not isinstance(info.get("offer_id"), str):
        raise ImportError("ozon_invalid_response")
    return {
        "external_id": pid,
        "marketplace_code": str(
            info.get("sku")
            or next((row["sku"] for row in info.get("sources", []) if row.get("sku")), "")
        ),
        "sku_aliases": list(
            dict.fromkeys(str(row["sku"]) for row in info.get("sources", []) if row.get("sku"))
        ),
        "vendor_code": info["offer_id"],
        "title": info["name"],
        "brand": ", ".join(values.get("бренд", [])),
        "colors": values.get("цвет товара", []),
        "size": ", ".join(size),
        "barcodes": list(dict.fromkeys(info.get("barcodes", []))),
        "photos": photos(info.get("primary_image", []) + info.get("images", [])),
        "group_id": group,
        "channel_skus": {channel: sorted(skus) for channel, skus in channel_skus.items()},
        "channels": channels,
        "seller_price": seller_price,
        "currency": price.get("currency_code"),
        "archived": info.get("is_archived", False),
    }
