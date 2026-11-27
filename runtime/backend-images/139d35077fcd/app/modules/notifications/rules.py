"""Small, deterministic rules. Unknown data never becomes a zero or an incident."""

from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

CATEGORIES = ("orders", "stock", "finance", "supplies", "connection")
PERMISSIONS = {
    "stock": "inventory.read",
    "supply": "inventory.read",
    "orders_drop": "analytics.read",
    "digest": "analytics.read",
    "finance": "finance.read",
    "token_expiring": "connection",
    "sync_failed": "connection",
    "stock_stale": "inventory.read",
    "import_ready": "analytics.read",
}
CATEGORY = {
    "stock": "stock",
    "stock_stale": "stock",
    "orders_drop": "orders",
    "digest": "digest",
    "finance": "finance",
    "supply": "supplies",
    "token_expiring": "connection",
    "sync_failed": "connection",
    "import_ready": "connection",
}


def local_time(now, settings):
    return now.astimezone(ZoneInfo(settings.timezone))


def is_quiet(now, settings):
    hour = local_time(now, settings).hour
    start, end = settings.quiet_start, settings.quiet_end
    return (
        (start <= hour < end)
        if start < end
        else (hour >= start or hour < end)
        if start != end
        else False
    )


def russian_days(value):
    days = max(1, int(Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING)))
    form = (
        "дней"
        if 11 <= days % 100 <= 14
        else "день"
        if days % 10 == 1
        else "дня"
        if days % 10 in (2, 3, 4)
        else "дней"
    )
    return f"{days} {form}"


def money(value, currency="RUB"):
    if value is None:
        return "—"
    number = format(Decimal(str(value)).quantize(Decimal(1)), ",").replace(",", " ")
    return f"{number} {'₽' if currency == 'RUB' else currency}"


def stock_events(items, threshold=3):
    for item in items:
        if not item.get("fresh") or item.get("status") != "ready":
            continue
        cover = item.get("days")
        if item.get("units") is None or cover is None or Decimal(str(cover)) > threshold:
            continue
        empty = item.get("units") == 0
        yield {
            "key": f"stock:{item['id']}",
            "kind": "stock",
            "severity": "high",
            "title": f"{item['name']}: нет на FBO" if empty else f"{item['name']} скоро закончится",
            "body": "На FBO больше нет товара."
            if empty
            else f"На FBO хватит на {russian_days(cover)}.",
            "data": {
                "section": "stock",
                "product_id": item["id"],
                "product_name": item["name"],
                "metrics": [
                    {"label": "На складе", "value": f"{item['units']} шт."},
                    {"label": "Запас", "value": "0 дней" if empty else russian_days(cover)},
                ],
                "advice": "Проверьте пополнение и срок следующей поставки.",
            },
        }


def order_event(days, today, currency):
    by_day = {row["day"]: row for row in days if row.get("orders") is not None}
    target = today - timedelta(days=1)
    current = by_day.get(str(target))
    base = [by_day.get(str(target - timedelta(days=7 * n))) for n in (1, 2, 3)]
    base = [row for row in base if row is not None]
    if current is None or len(base) < 2:
        return None
    average = sum(Decimal(row["orders"]) for row in base) / len(base)
    if average < 10 or current["orders"] >= average * Decimal(".7"):
        return None
    drop = int((1 - Decimal(current["orders"]) / average) * 100)
    return {
        "key": f"orders:{target}",
        "kind": "orders_drop",
        "severity": "medium",
        "title": f"Заказы ниже обычного на {drop}%",
        "body": f"За {target:%d.%m}: {current['orders']} шт. вместо обычных {round(average)}.",
        "data": {
            "section": "orders",
            "date_from": str(target),
            "date_to": str(target),
            "metrics": [
                {"label": "Заказано", "value": f"{current['orders']} шт."},
                {
                    "label": "Сумма",
                    "value": money(
                        None
                        if "orders_amount" in current.get("partial_amounts", [])
                        else current.get("orders_amount"),
                        currency,
                    ),
                },
                {"label": "Обычно", "value": f"{round(average)} шт."},
            ],
            "advice": "Проверьте наличие, доступность карточек и изменение цены.",
        },
    }


def financial_events(current, previous, period, currency):
    if not current or not previous or not current["complete"] or not previous["complete"]:
        return
    old = {row["key"]: row for row in previous["groups"]}
    allowed = {
        "fees",
        "logistics",
        "warehouse",
        "advertising",
        "subscriptions",
        "penalties",
        "services",
    }
    for row in current["groups"]:
        before = old.get(row["key"], {}).get("amount")
        if row["key"] not in allowed or before is None or row.get("amount") is None:
            continue
        value, baseline = Decimal(row["amount"]), Decimal(before)
        if baseline <= 0 or value < baseline * Decimal("1.2") or value - baseline < 1000:
            continue
        change = int((value / baseline - 1) * 100)
        yield {
            "key": f"finance:{row['key']}:{period['date_to']}",
            "kind": "finance",
            "severity": "medium",
            "title": f"{row['title']}: расходы выросли на {change}%",
            "body": f"За период — {money(value, currency)}. Проверьте детализацию.",
            "data": {
                "section": "finance",
                **period,
                "group": row["key"],
                "metrics": [
                    {"label": "За период", "value": money(value, currency)},
                    {"label": "Предыдущий период", "value": money(baseline, currency)},
                ],
                "advice": "Проверьте операции, за счёт которых выросла сумма.",
            },
        }


def supply_events(rows, today):
    for row in rows:
        if row.get("status") not in {"planned", "ready_to_ship", "shipped"}:
            continue
        planned = row.get("planned_date")
        if (
            not planned
            or date.fromisoformat(planned) >= today
            or row.get("actual_date")
            or row.get("rejected")
            or row.get("accepted_quantity")
        ):
            continue
        identifier = str(row.get("external_id") or row.get("id") or row.get("supply_id") or "")
        if not identifier:
            continue
        yield {
            "key": f"supply:{identifier}",
            "kind": "supply",
            "severity": "medium",
            "title": "Проверьте дату поставки",
            "body": "Плановая дата прошла. Приёмка не подтверждена.",
            "data": {
                "section": "supplies",
                "supply_id": identifier,
                "metrics": [
                    {"label": "Поставка", "value": identifier},
                    {
                        "label": "Плановая дата",
                        "value": date.fromisoformat(planned).strftime("%d.%m.%Y"),
                    },
                ],
                "advice": "Уточните дату прибытия и статус приёмки в кабинете.",
            },
        }


def digest_day(days, now, settings, today):
    local = local_time(now, settings)
    if local.hour < settings.digest_hour:
        return None
    target = local.date() if settings.digest_mode == "evening" else local.date() - timedelta(days=1)
    earliest = target - timedelta(days=1) if settings.digest_mode == "evening" else target
    ready = [
        row
        for row in days
        if row.get("orders") is not None
        and row.get("orders_amount") is not None
        and earliest <= date.fromisoformat(row["day"]) <= target
    ]
    return max(ready, key=lambda row: row["day"], default=None)
