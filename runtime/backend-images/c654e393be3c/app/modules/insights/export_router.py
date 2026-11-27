import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.modules.accounts.access import allows
from app.modules.accounts.reporting import reporting_stores
from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.finance.xlsx import build_template
from app.modules.insights import compute, funnel, ozon_read
from app.modules.supplies.export import text

router = APIRouter(prefix="/workspaces/{workspace_id}/insights", tags=["Insights"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FIELDS = [
    ("impressions", "Показы"),
    ("opens", "Открытия"),
    ("carts", "В корзину"),
    ("orders", "Заказано, шт."),
    ("orders_amount", "Заказано, сумма"),
    ("buyouts", "Выкуплено, шт."),
    ("buyouts_amount", "Выкуплено, сумма"),
    ("cancellations", "Отмены и возвраты, шт."),
    ("cancellations_amount", "Отмены и возвраты, сумма"),
    ("add_to_cart_percent", "Конверсия в корзину, %"),
    ("cart_to_order_percent", "Конверсия в заказ, %"),
    ("buyout_percent", "Выкуп, %"),
]


@router.get(
    "/funnel/export",
    operation_id="analyticsSalesExport",
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
def export_sales(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    date_from: date,
    date_to: date,
    store_id: UUID | None = None,
    format: Literal["csv", "xlsx"] = "xlsx",
    granularity: Literal["products", "days", "sizes"] = "products",
    price_basis: Literal["customer", "seller"] = "customer",
):
    member = require_workspace(db, identity, workspace_id)
    if not allows(member, "analytics.read") or not allows(member, "reports.export"):
        raise HTTPException(403, "Нет доступа к экспорту аналитики.")
    params = compute.period_params(date_from, date_to)
    stores = reporting_stores(db, workspace_id, store_id, feature="analytics")
    headers = [
        "Кабинет",
        "Площадка",
        "С",
        "По",
        "Дата" if granularity == "days" else "Артикул продавца",
        "Артикул площадки",
        "Товар",
        "Валюта",
        *[label for _, label in FIELDS],
        "Состояние данных",
    ]
    if granularity == "sizes":
        from app.modules.insights import size_export

        if not stores or any(store.marketplace != "wildberries" for store in stores):
            raise HTTPException(422, "Для выгрузки по размерам выберите кабинет WB.")
        headers = size_export.HEADERS
    rows = []
    for store in stores:
        start, end = (
            date.fromisoformat(params["date_from"]),
            date.fromisoformat(params["date_to"]),
        )
        if granularity == "sizes":
            rows.extend(
                size_export.rows(db, request.app.state.vault, workspace_id, store, start, end)
            )
            if len(rows) > 50000:
                raise HTTPException(422, "Уточните период или выберите один кабинет.")
            continue
        if store.marketplace == "ozon":
            start, end = ozon_read.period(start, end)
            ozon_read.ensure_range(db, workspace_id, store.id, start)
            data = ozon_read.report(
                db,
                request.app.state.vault,
                workspace_id,
                store.id,
                start,
                end,
                product_limit=None,
                price_basis=price_basis,
            )
        else:
            data = funnel.report(
                db,
                request.app.state.vault,
                workspace_id,
                store.id,
                start,
                end,
                product_limit=None,
            )
        state = data.get("status", "")
        if store.marketplace == "ozon" and granularity == "products":
            covered = data.get("product_traffic_known_days", 0)
            if covered < data["period_days"]:
                state += f"; трафик по товарам: {covered} из {data['period_days']} дней"
        for item in data["daily"] if granularity == "days" else data["products"]:
            values = []
            for key, _ in FIELDS:
                value = item.get(key)
                values.append(Decimal(str(value)) if value is not None else "")
            rows.append(
                [
                    store.name,
                    "Ozon" if store.marketplace == "ozon" else "WB",
                    str(start),
                    str(end),
                    item.get("day", "") if granularity == "days" else item.get("vendor_code", ""),
                    item.get("marketplace_code") or item.get("nm_id", ""),
                    item.get("title", ""),
                    data.get("currency") or "",
                    *values,
                    state,
                ]
            )
            if len(rows) > 50000:
                raise HTTPException(422, "Уточните период или выберите один кабинет для выгрузки.")
    if format == "xlsx":
        payload = build_template(headers, rows, sheet_name="Аналитика", numeric=True)
    else:
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow([text(value) if isinstance(value, str) else value for value in row])
        payload = ("\ufeff" + output.getvalue()).encode("utf-8")
    db.commit()
    return Response(
        payload,
        media_type=XLSX if format == "xlsx" else "text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="perk-sales-{date_from}-{date_to}.{format}"'
            ),
            "Cache-Control": "no-store",
        },
    )
