"""WB operational size detail. Event dates are explicit, never presented as funnel cohorts."""

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.insights.compute import sales_known_days
from app.modules.sync.analytics import record_context
from app.modules.sync.models import WBRecord

HEADERS = [
    "Кабинет",
    "С",
    "По",
    "Артикул продавца",
    "Артикул WB",
    "Размер",
    "Баркод",
    "Заказы по дате заказа, шт.",
    "Заказы, сумма",
    "Отмены, шт.",
    "Выкупы по дате продажи, шт.",
    "Выкупы, сумма",
    "Возвраты, шт.",
    "Заказы: данные с",
    "Заказы: данные по",
    "Выкупы: данные с",
    "Выкупы: данные по",
    "Состояние данных",
    "Валюта",
]


def rows(db, vault, wid, store, start, end):
    coverage = {
        source: sales_known_days(db, wid, store.id, source)
        for source in (Source.ORDERS, Source.SALES)
    }
    present = {
        source: bool(first and through and first <= end and through >= start)
        for source, (first, through) in coverage.items()
    }
    if not any(present.values()):
        raise HTTPException(
            409,
            "Нет сохранённой детализации WB по размерам за этот период. "
            "WB отдаёт заказы и продажи только за последние 90 дней. "
            "Более старые дни доступны, если PERK сохранил их ранее.",
        )
    # Legacy sales records did not persist techSize. Resolve only an exact unique barcode
    # within its original nmID, never infer from the article or product name.
    from app.modules.catalog.service import products

    catalogue = products(
        db,
        vault,
        wid,
        [store],
        currency="RUB",
        query="",
        only_stock=False,
        missing_cost=False,
        can_stock=False,
        can_cost=False,
        limit=None,
        offset=0,
    )
    sizes = defaultdict(set)
    for product in catalogue.items:
        for variant in product.variants:
            for barcode in variant.barcodes:
                if variant.size:
                    sizes[(product.nm_id, barcode)].add(variant.size)
    grouped = defaultdict(
        lambda: {
            "orders": 0,
            "buyouts": 0,
            "cancellations": 0,
            "returns": 0,
            "orders_amount": Decimal(0),
            "buyouts_amount": Decimal(0),
            "missing": set(),
        }
    )
    records = db.scalars(
        select(WBRecord)
        .where(*scope(WBRecord, wid, store.id), WBRecord.source.in_([Source.ORDERS, Source.SALES]))
        .execution_options(yield_per=500)
    )
    count = 0
    for row in records:
        count += 1
        if count > 500000:
            raise HTTPException(
                422, "Для размерной выгрузки выберите один кабинет с меньшим каталогом."
            )
        data = json.loads(
            vault.open(row.ciphertext, record_context(wid, store.id, row.source, row.record_key))
        )
        day = date.fromisoformat(data["date"][:10])
        first, through = coverage[row.source]
        if not (start <= day <= end and first and first <= day <= through):
            continue
        size = data.get("size", "")
        known_sizes = sizes[(data["nm_id"], data.get("barcode", ""))]
        size = size or (next(iter(known_sizes)) if len(known_sizes) == 1 else "")
        key = (data["nm_id"], data.get("vendor_code", ""), size, data.get("barcode", ""))
        target = grouped[key]
        if row.source == Source.ORDERS:
            field = "orders"
            target["orders"] += 1
            target["cancellations"] += int(data["is_cancel"])
        elif data["kind"] == "sale":
            field = "buyouts"
            target["buyouts"] += 1
        else:
            target["returns"] += 1
            continue
        price = data.get("finished_price")
        if price is None:
            target["missing"].add(field)
        else:
            target[field + "_amount"] += Decimal(price)
        if len(grouped) > 50000:
            raise HTTPException(422, "Слишком много размерных позиций для одной выгрузки.")
    if not grouped:
        raise HTTPException(
            409, "В сохранённых данных за выбранный период нет заказов или выкупов по размерам."
        )
    complete = all(
        first and first <= start and through >= end for first, through in coverage.values()
    )
    result = []
    for (nm, vendor, size, barcode), value in sorted(grouped.items()):
        known_sizes = sizes[(nm, barcode)]
        size = size or (next(iter(known_sizes)) if len(known_sizes) == 1 else "")

        def counts(field, source, value=value):
            return value[field] if present[source] else ""

        def amount(field, source, value=value):
            return (
                value[field + "_amount"]
                if present[source] and field not in value["missing"]
                else ""
            )

        dates = [
            str(max(first, start)) if first and present[source] else ""
            for source, (first, _) in coverage.items()
        ]
        ends = [
            str(min(through, end)) if through and present[source] else ""
            for source, (_, through) in coverage.items()
        ]
        result.append(
            [
                store.name,
                str(start),
                str(end),
                vendor,
                nm,
                size,
                barcode,
                counts("orders", Source.ORDERS),
                amount("orders", Source.ORDERS),
                counts("cancellations", Source.ORDERS),
                counts("buyouts", Source.SALES),
                amount("buyouts", Source.SALES),
                counts("returns", Source.SALES),
                dates[0],
                ends[0],
                dates[1],
                ends[1],
                "Полные" if complete else "Часть периода",
                "Валюта кабинета WB",
            ]
        )
    return result
