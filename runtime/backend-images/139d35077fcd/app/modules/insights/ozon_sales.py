"""Order-date cohorts. Keep delivery/return counts separate from financial accounting."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from app.integrations.ozon.operations import MOSCOW
from app.integrations.ozon.transport import OzonImportError
from app.modules.finance.precision import money

COUNT_FIELDS = ("orders", "buyouts", "cancellations")
AMOUNT_FIELDS = tuple(field + "_amount" for field in COUNT_FIELDS)
AVAILABLE = (*COUNT_FIELDS, *AMOUNT_FIELDS, "buyout_percent")
STATES = {
    "awaiting_registration",
    "acceptance_in_progress",
    "awaiting_approve",
    "awaiting_packaging",
    "awaiting_deliver",
    "arbitration",
    "client_arbitration",
    "delivering",
    "driver_pickup",
    "delivered",
    "cancelled",
    "not_accepted",
    "sent_by_seller",
}


def integer(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise ValueError("quantity")
    return value


def number(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result.adjusted() > 30:
        raise ValueError("number")
    return result


def day_of(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone")
    return stamp.astimezone(MOSCOW).date()


def posting(raw, channel):
    status = raw["status"]
    if status not in STATES:
        raise OzonImportError("ozon_unknown_status")
    # Ozon also exposes logistics orders from external sales channels.
    if (raw.get("external_order") or {}).get("is_external") is True:
        return None
    # Ozon list filters use acceptance into processing, not draft posting creation.
    # A draft may be created several days before the order is confirmed.
    stamp = raw.get("in_process_at")
    financial = {}
    for value in (raw.get("financial_data") or {}).get("products", []):
        sku = str(integer(value["product_id"], positive=True))
        if sku in financial:
            raise OzonImportError("ozon_duplicate_product")
        financial[sku] = value
    items, skus = [], set()
    for product in raw["products"]:
        sku = str(integer(product["sku"], positive=True))
        if sku in skus:
            raise OzonImportError("ozon_duplicate_product")
        skus.add(sku)
        # The ordinary price excludes Ozon's discount. Never substitute it for customer price.
        price = financial.get(sku, {}).get("customer_price") or {}
        if not isinstance(price, dict):
            raise ValueError("price_shape")
        amount = number(price.get("amount"))
        currency = price.get("currency") or (product.get("price") or {}).get("currency")
        if currency is not None and (not isinstance(currency, str) or len(currency) != 3):
            raise ValueError("currency")
        items.append(
            {
                "sku": sku,
                "quantity": integer(product["quantity"], positive=True),
                "price": format(amount, "f") if amount is not None else None,
                "currency": currency,
                "seller_price": str(number((product.get("price") or {}).get("amount")))
                if (product.get("price") or {}).get("amount") is not None
                else None,
                "seller_currency": (product.get("price") or {}).get("currency"),
            }
        )
    if not items or not isinstance(raw["posting_number"], str) or not raw["posting_number"]:
        raise ValueError("posting")
    return {
        "number": raw["posting_number"],
        "day": day_of(stamp),
        "status": status,
        "channel": channel,
        "items": items,
    }


def returned(raw):
    product = raw["product"]
    logistic = raw.get("logistic") or {}
    # An opened claim is not yet a confirmed returned unit.
    status = ((raw.get("visual") or {}).get("status") or {}).get("sys_name")
    confirmed = bool(logistic.get("final_moment")) or status in {
        "ReceivedBySeller",
        "ReturnedToOzon",
    }
    return {
        "id": integer(raw["id"], positive=True),
        "number": raw["posting_number"],
        "sku": str(integer(product["sku"], positive=True)),
        "quantity": integer(product["quantity"], positive=True),
        "confirmed": confirmed,
        "exemplars": sorted(
            {
                str(row.get("exemplar_id") or row.get("id"))
                for row in raw.get("exemplars", [])
                if row.get("exemplar_id") or row.get("id")
            }
        ),
    }


def blank():
    return {
        "currencies": set(),
        "counts": dict.fromkeys(COUNT_FIELDS, 0),
        "amounts": {field: Decimal(0) for field in AMOUNT_FIELDS},
        "missing": set(),
        "priced": dict.fromkeys(COUNT_FIELDS, 0),
    }


def figures(value, allow_partial=False):
    counts = value["counts"]
    resolved = counts["buyouts"] + counts["cancellations"]
    return {
        "opens": None,
        "carts": None,
        "wishlist": None,
        **counts,
        **{
            field: None
            if (
                field in value["missing"]
                and not (allow_partial and value["priced"][field.removesuffix("_amount")])
            )
            or len(value["currencies"]) > 1
            else money(amount)
            for field, amount in value["amounts"].items()
        },
        "add_to_cart_percent": None,
        "cart_to_order_percent": None,
        "open_to_order_percent": None,
        "buyout_percent": format(
            (Decimal(counts["buyouts"]) * 100 / resolved).quantize(Decimal("0.1")), "f"
        )
        if resolved
        else None,
    }


def aggregate(postings, returns, start, end):
    """Never add a cancellation twice; repeated physical exemplars are counted once."""
    claimed = defaultdict(lambda: {"exemplars": set(), "anonymous": 0})
    for row in returns:
        if not row["confirmed"]:
            continue
        target = claimed[(row["number"], row["sku"])]
        target["exemplars"].update(row["exemplars"])
        target["anonymous"] += max(0, row["quantity"] - len(row["exemplars"]))
    days = {
        start + timedelta(days=index): {
            "totals": blank(),
            "products": {},
            "price_items": [],
            "channel_orders": {"fbo": {}, "fbs": {}},
        }
        for index in range((end - start).days + 1)
    }
    with localcontext() as context:
        context.prec = 64
        for row in postings:
            target = days[row["day"]]
            for item in row["items"]:
                quantity = item["quantity"]
                channel = target["channel_orders"].get(row.get("channel"))
                if channel is not None:
                    channel[item["sku"]] = channel.get(item["sku"], 0) + quantity
                returned_units = claimed[(row["number"], item["sku"])]
                lost = min(quantity, len(returned_units["exemplars"]) + returned_units["anonymous"])
                cancelled = quantity if row["status"] == "cancelled" else lost
                bought = quantity - lost if row["status"] == "delivered" else 0
                values = {"orders": quantity, "buyouts": bought, "cancellations": cancelled}
                target["price_items"].append(
                    {
                        "key": row["number"],
                        "sku": item["sku"],
                        "price": item["price"],
                        "currency": item["currency"],
                        "seller_price": item.get("seller_price"),
                        "seller_currency": item.get("seller_currency"),
                        "units": values,
                    }
                )
                for subtotal in (
                    target["totals"],
                    target["products"].setdefault(item["sku"], blank()),
                ):
                    if item["currency"]:
                        subtotal["currencies"].add(item["currency"])
                    for field, units in values.items():
                        subtotal["counts"][field] += units
                        if units and (item["price"] is None or not item["currency"]):
                            subtotal["missing"].add(field + "_amount")
                        elif units:
                            subtotal["amounts"][field + "_amount"] += Decimal(item["price"]) * units
        return {
            day: {
                "date_basis": "in_process_at",
                "price_basis": "customer_v1",
                "customer_prices_version": 2,
                "price_items": value["price_items"],
                "channel_orders": value["channel_orders"],
                "currencies": sorted(value["totals"]["currencies"]),
                "totals": figures(value["totals"]),
                "products": {sku: figures(product) for sku, product in value["products"].items()},
            }
            for day, value in days.items()
        }


def combine(rows, *, currency_known=True, allow_partial=False):
    """All selected confirmed days must contain a metric before it becomes known."""
    if not rows:
        return {key: None for key in figures(blank())}
    result = {}
    with localcontext() as context:
        context.prec = 64
        for field in (*COUNT_FIELDS, *AMOUNT_FIELDS):
            values = [row[field] for row in rows]
            if allow_partial and field in AMOUNT_FIELDS:
                partial = any(
                    row[field] is None or field in row.get("partial_amounts", []) for row in rows
                )
                values = [
                    row[field]
                    for row in rows
                    if row[field] is not None
                    and (not partial or row[field.removesuffix("_amount")] > 0)
                ]
            result[field] = (
                None
                if not values or any(value is None for value in values)
                else (
                    money(sum((Decimal(value) for value in values), Decimal(0)))
                    if field in AMOUNT_FIELDS and currency_known
                    else sum(values)
                    if field in COUNT_FIELDS
                    else None
                )
            )
        denominator = (result["buyouts"] or 0) + (result["cancellations"] or 0)
        result.update(
            {
                key: None
                for key in (
                    "opens",
                    "carts",
                    "wishlist",
                    "add_to_cart_percent",
                    "cart_to_order_percent",
                    "open_to_order_percent",
                )
            }
        )
        result["buyout_percent"] = (
            format((Decimal(result["buyouts"]) * 100 / denominator).quantize(Decimal("0.1")), "f")
            if denominator
            else None
        )
    if allow_partial:
        result["partial_amounts"] = [
            field
            for field in AMOUNT_FIELDS
            if any(row[field] is None or field in row.get("partial_amounts", []) for row in rows)
        ]
    return result


def reprice(data, prices, currency=None, price_basis="customer"):
    """Rebuild amounts from confirmed buyer prices; counts never depend on price availability."""
    totals, products = blank(), {}
    with localcontext() as context:
        context.prec = 64
        for item in data["price_items"]:
            if price_basis == "seller":
                quote = {"price": item.get("seller_price"), "currency": item.get("seller_currency")}
            else:
                quote = {"price": item["price"], "currency": item["currency"]}
                if quote["price"] is None or (currency and quote["currency"] != currency):
                    quote = prices.get((item["key"], item["sku"])) or quote
            if currency and quote.get("currency") != currency:
                quote = {"price": None, "currency": currency}
            for value in (totals, products.setdefault(item["sku"], blank())):
                if quote.get("currency"):
                    value["currencies"].add(quote["currency"])
                for field, units in item["units"].items():
                    value["counts"][field] += units
                    if units and quote.get("price") is None:
                        value["missing"].add(field + "_amount")
                    elif units:
                        value["priced"][field] += units
                        value["amounts"][field + "_amount"] += Decimal(quote["price"]) * units
        return {
            **data,
            "currencies": sorted(totals["currencies"]),
            "totals": {**figures(totals, True), "partial_amounts": sorted(totals["missing"])},
            "products": {
                sku: {**figures(value, True), "partial_amounts": sorted(value["missing"])}
                for sku, value in products.items()
            },
        }
