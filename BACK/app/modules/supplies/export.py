"""A requirements report, not an unverified marketplace upload template."""

import csv
from io import StringIO
from types import SimpleNamespace

from fastapi import HTTPException

from app.modules.supplies.plan_variants import allocation


def text(value):
    value = str(value or "")
    # Marketplace/seller text cannot become a spreadsheet formula.
    return (
        "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
    )


def identifier(value):
    # Keep leading zeroes and long native IDs when opening CSV in Excel.
    return "'" + str(value) if value else ""


def plan_items_csv(plan):
    _, error = allocation(plan.items)
    if error:
        raise HTTPException(409, error)
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(
        [
            "План",
            "Кабинет",
            "Площадка",
            "Склад / кластер",
            "Артикул продавца",
            "Артикул площадки",
            "ID варианта",
            "Размер",
            "Штрихкод",
            "Количество, шт.",
        ]
    )
    for item in plan.items:
        for variant in item.variants:
            if variant.quantity:
                writer.writerow(
                    [
                        text(plan.title),
                        text(plan.store_name),
                        "Ozon" if plan.marketplace == "ozon" else "WB",
                        text(plan.destination),
                        identifier(item.vendor_code),
                        identifier(item.marketplace_code or item.nm_id),
                        identifier(variant.external_id),
                        text(variant.size),
                        identifier(variant.barcode),
                        variant.quantity,
                    ]
                )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def plan_csv(plan):
    data = SimpleNamespace(
        items=[row for row in plan.items if row.quantity],
        target_days=plan.target_days,
        lead_time_days=plan.lead_time_days,
        partial=plan.source_partial,
        loading=False,
        updated_at=plan.source_updated_at,
    )
    rows = csv.reader(StringIO(requirements_csv(data).decode("utf-8-sig")), delimiter=";")
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["План", "Склад / кластер", *next(rows)])
    for row in rows:
        writer.writerow([text(plan.title), text(plan.destination), *row])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def requirements_csv(data):
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(
        [
            "Кабинет",
            "Площадка",
            "Артикул продавца",
            "Артикул площадки",
            "Штрихкоды",
            "Товар",
            "Направление",
            "Остаток FBO",
            "Остаток FBS для зачёта",
            "Снижение потребности за счёт FBS, шт.",
            "В оформленных поставках, шт.",
            "Снижение потребности за счёт поставок, шт.",
            "Спрос в день",
            "Запас сейчас, дней",
            "Потребность, шт.",
            "В коробе, шт.",
            "Коробов",
            "К поставке, шт.",
            "Запас после поступления, дней",
            "Доставка и приёмка, дней",
            "Состояние данных",
            "Обновлено",
        ]
    )
    for item in data.items:
        writer.writerow(
            [
                text(item.store_name),
                "Ozon" if item.marketplace == "ozon" else "WB",
                identifier(item.vendor_code),
                identifier(item.marketplace_code or item.nm_id),
                identifier(" · ".join(item.barcodes)),
                text(item.title),
                text(item.destination_name),
                item.stock,
                item.fbs_stock,
                item.fbs_reduction,
                item.incoming_quantity if item.incoming_quantity is not None else "",
                item.incoming_reduction,
                item.daily_orders.replace(".", ","),
                item.days_of_stock.replace(".", ","),
                item.required_quantity,
                item.box_multiple,
                item.quantity // item.box_multiple,
                item.quantity,
                data.target_days,
                data.lead_time_days,
                "Частичные" if data.partial or data.loading else "Готовые",
                data.updated_at.isoformat() if data.updated_at else "",
            ]
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def requirements_xlsx(data):
    from decimal import Decimal

    from app.modules.finance.xlsx import build_template

    headers = next(csv.reader(StringIO(requirements_csv(data).decode("utf-8-sig")), delimiter=";"))
    rows = [
        [
            item.store_name,
            "Ozon" if item.marketplace == "ozon" else "WB",
            item.vendor_code,
            item.marketplace_code or item.nm_id,
            " · ".join(item.barcodes),
            item.title,
            item.destination_name,
            item.stock,
            item.fbs_stock,
            item.fbs_reduction,
            item.incoming_quantity,
            item.incoming_reduction,
            Decimal(item.daily_orders),
            Decimal(item.days_of_stock),
            item.required_quantity,
            item.box_multiple,
            item.quantity // item.box_multiple,
            item.quantity,
            data.target_days,
            data.lead_time_days,
            "Частичные" if data.partial or data.loading else "Готовые",
            data.updated_at.isoformat() if data.updated_at else "",
        ]
        for item in data.items
    ]
    return build_template(headers, rows, sheet_name="Потребность", numeric=True)
