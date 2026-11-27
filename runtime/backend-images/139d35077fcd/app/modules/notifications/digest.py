"""One daily summary per workspace, from the same confirmed day in every allowed store."""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.notifications import rules


def build(entries, stamp, settings, name, *, inventory_allowed, finance_allowed, costs_allowed):
    local = rules.local_time(stamp, settings)
    if not settings.digest_enabled or local.hour < settings.digest_hour or not entries:
        return None
    target = local.date() if settings.digest_mode == "evening" else local.date() - timedelta(days=1)
    eligible = {str(target)}
    if settings.digest_mode == "evening":
        eligible.add(str(target - timedelta(days=1)))
    days = []
    for _store, data in entries:
        if data is None:
            return None
        known = {
            row["day"]: row
            for row in data["daily"]
            if row.get("orders") is not None
            and row.get("orders_amount") is not None
            and "orders_amount" not in row.get("partial_amounts", [])
        }
        eligible &= known.keys()
        days.append(known)
    if not eligible:
        return None
    day = max(eligible)
    rows = [known[day] for known in days]
    units = sum(row["orders"] for row in rows)
    currencies = {data["currency"] for _, data in entries}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    amount = sum((Decimal(row["orders_amount"]) for row in rows), Decimal(0)) if currency else None
    earlier = str(date.fromisoformat(day) - timedelta(days=7))
    previous = [known.get(earlier) for known in days]
    change = None
    if currency and all(row is not None for row in previous):
        baseline = sum((Decimal(row["orders_amount"]) for row in previous), Decimal(0))
        if baseline > 0:
            change = ((amount / baseline - 1) * 100).quantize(Decimal(".1"))
    comparison = f", {change:+}%" if change is not None else ""
    metrics = [{"label": "Заказано", "value": f"{units} шт."}]
    if amount is not None:
        metrics.append({"label": "Сумма", "value": rules.money(amount, currency)})
    if change is not None:
        metrics.append({"label": f"К {date.fromisoformat(earlier):%d.%m}", "value": f"{change:+}%"})
    leaders, actions, permissions = [], [], set()
    for (store, data), row in zip(entries, rows, strict=True):
        if len(entries) > 1:
            metrics.append(
                {
                    "label": store.name,
                    "value": (
                        f"{rules.money(row['orders_amount'], data['currency'])} · "
                        f"{row['orders']} шт."
                    ),
                }
            )
        if data.get("leaders_day") == day:
            leaders.extend((store.name, product) for product in data.get("leaders", []))
        if (
            inventory_allowed
            and data.get("stock_complete")
            and settings.categories.get("stock", True)
        ):
            low = list(rules.stock_events(data.get("stock", [])))
            if low and len(actions) < 2:
                permissions.add("inventory.read")
                actions.append(f"проверить пополнение: {low[0]['data']['product_name']}")
        if finance_allowed and settings.categories.get("finance", True):
            alerts = list(
                rules.financial_events(
                    data.get("finance"),
                    data.get("previous_finance"),
                    data.get("finance_period", {}),
                    data["currency"],
                )
            )
            if alerts and len(actions) < 2:
                permissions.add("finance.read")
                actions.append("проверить выросшие расходы: " + store.name)
        if (
            costs_allowed
            and settings.categories.get("finance", True)
            and data.get("missing_cost_count")
        ):
            permissions.add("profit.read")
            metrics.append(
                {
                    "label": "Без себестоимости · " + store.name,
                    "value": f"{data['missing_cost_count']} вариантов",
                }
            )
    leaders.sort(
        key=lambda item: (
            Decimal(item[1].get("orders_amount") or 0)
            if currency
            else Decimal(item[1].get("orders") or 0)
        ),
        reverse=True,
    )
    for shop, item in leaders[:3]:
        title = (
            item.get("title")
            or item.get("vendor_code")
            or item.get("nm_id")
            or item.get("key", "Товар")
        )
        metrics.append(
            {"label": f"Лидер · {title} · {shop}", "value": f"{item.get('orders', 0)} шт."}
        )
    return {
        "key": f"digest:{day}",
        "kind": "digest",
        "required_permissions": sorted(permissions),
        "severity": "info",
        "title": f"Итоги {date.fromisoformat(day):%d.%m} · {name}",
        "body": f"Заказано на {rules.money(amount, currency)}{comparison}. Всего {units} шт."
        if amount is not None
        else f"Заказано {units} шт.",
        "data": {
            "section": "orders",
            "store_name": name,
            "date_from": day,
            "date_to": day,
            "metrics": metrics,
            "advice": "На завтра: " + "; ".join(actions) + "." if actions else None,
        },
    }
