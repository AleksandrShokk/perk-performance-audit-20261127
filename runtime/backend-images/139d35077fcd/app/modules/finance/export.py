"""Detailed financial exports use exactly the same scoped reports as the screen."""

import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.db.session import set_actor
from app.modules.accounts.access import allows
from app.modules.accounts.reporting import reporting_stores
from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.finance.overview import percent
from app.modules.finance.precision import money_precision
from app.modules.finance.xlsx import build_template, sheet_names
from app.modules.supplies.export import text

router = APIRouter(prefix="/workspaces/{workspace_id}/finance", tags=["Finance"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = [
    "Кабинет",
    "Площадка",
    "Раздел",
    "Подпункт",
    "Сумма",
    "Единица",
    "Доля выручки, %",
    "Валюта",
    "С",
    "По",
    "Состояние",
]


@money_precision()
def report_rows(report, cabinet, marketplace, can_profit):
    status = (
        "Частичный отчёт" if report.is_partial or not report.period_covered else "Готовый отчёт"
    )

    def row(group, title, value, unit="money"):
        share = percent(value, report.totals.seller_revenue) if unit == "money" else None
        return [
            cabinet,
            marketplace,
            group,
            title,
            Decimal(value) if value is not None else None,
            {"money": "Деньги", "units": "шт.", "percent": "%"}[unit],
            Decimal(share) if share is not None else None,
            report.currency if unit == "money" else "",
            str(report.date_from),
            str(report.date_to),
            status,
        ]

    totals = [
        ("Выручка продавца", report.totals.seller_revenue),
        ("Расходы", report.totals.expenses_before_tax),
        ("К перечислению", report.totals.settlement),
    ]
    if can_profit:
        totals.extend(
            [
                ("Прибыль до налогов", report.totals.profit_before_tax),
                ("НДС · оценка", report.taxes.vat),
                ("Налог · оценка", report.taxes.tax),
                ("Чистая прибыль · оценка", report.taxes.net_profit),
            ]
        )
    rows = [row("Сводка", name, amount) for name, amount in totals]
    for group in report.groups:
        if not can_profit and group.key == "cogs":
            continue
        rows.append(row(group.title, "Итого по разделу", group.amount))
        rows.extend(row(group.title, item.title, item.amount, item.unit) for item in group.lines)
    return rows


@router.get(
    "/export",
    operation_id="financeOverviewExport",
    response_class=Response,
    responses={
        200: {
            "content": {
                XLSX: {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
def export_finance(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    date_from: date,
    date_to: date,
    store_id: UUID | None = None,
    format: Literal["xlsx", "csv"] = "xlsx",
):
    from app.modules.insights.business import finance_overview

    member = require_workspace(db, identity, workspace_id)
    if not allows(member, "finance.read") or not allows(member, "reports.export"):
        raise HTTPException(403, "Нет доступа к выгрузке финансов.")
    stores = reporting_stores(db, workspace_id, store_id, feature="finance")
    can_profit = allows(member, "profit.read")
    report = finance_overview(
        workspace_id, date_from, date_to, request, db, identity, currency=None, store_id=store_id
    )
    rows = report_rows(
        report,
        stores[0].name if len(stores) == 1 else "Все кабинеты",
        ("Ozon" if stores[0].marketplace == "ozon" else "WB") if len(stores) == 1 else "WB / Ozon",
        can_profit,
    )
    sheets, details = [], []
    if len(stores) > 1:
        names = sheet_names(
            [f"{'Ozon' if s.marketplace == 'ozon' else 'WB'} {s.name}" for s in stores],
            reserved=["Сводка"],
        )
        for store, name in zip(stores, names, strict=True):
            # The screen reader commits scheduling; restore this transaction's RLS actor.
            set_actor(db, identity.user.id)
            child = finance_overview(
                workspace_id,
                date_from,
                date_to,
                request,
                db,
                identity,
                currency=None,
                store_id=store.id,
            )
            values = report_rows(
                child, store.name, "Ozon" if store.marketplace == "ozon" else "WB", can_profit
            )
            sheets.append((name, HEADERS, values))
            details.extend(values)
    if format == "xlsx":
        payload = build_template(
            HEADERS, rows, sheet_name="Сводка", numeric=True, extra_sheets=sheets
        )
    else:
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(HEADERS)
        for values in [*rows, *details]:
            writer.writerow(
                [
                    text(value)
                    if isinstance(value, str)
                    else str(value).replace(".", ",")
                    if isinstance(value, Decimal)
                    else value
                    for value in values
                ]
            )
        payload = ("\ufeff" + output.getvalue()).encode("utf-8")
    return Response(
        payload,
        media_type=XLSX if format == "xlsx" else "text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="perk-finance-{date_from}-{date_to}.{format}"'
            ),
            "Cache-Control": "no-store",
        },
    )
