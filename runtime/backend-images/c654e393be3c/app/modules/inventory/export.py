"""All selected cabinets, never just the currently visible table page."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.modules.accounts.access import allows
from app.modules.accounts.models import Workspace
from app.modules.accounts.reporting import reporting_stores
from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.finance.xlsx import build_template
from app.modules.inventory.overview import overview
from app.modules.inventory.overview_schemas import CoverageChannel

router = APIRouter(prefix="/workspaces/{workspace_id}/inventory", tags=["Inventory"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def number(value):
    return Decimal(value) if value is not None else None


def position_row(position, currency, can_cost):
    product = position.product
    row = [
        product.store_name,
        "Ozon" if product.marketplace == "ozon" else "WB",
        product.vendor_code,
        product.marketplace_code,
        product.title,
        ", ".join(product.colors),
        ", ".join(v.size for v in product.variants),
        ", ".join(sorted({b for v in product.variants for b in v.barcodes})),
        position.fbo.units,
        number(position.fbo.retail_value),
        position.fbs.units,
        number(position.fbs.retail_value),
    ]
    if can_cost:
        row.extend(
            [
                number(position.fbo.cost_value),
                number(position.fbs.cost_value),
                "Да" if position.fbo.cost_complete and position.fbs.cost_complete else "Нет",
            ]
        )
    status = {
        "ready": "Рассчитан",
        "no_orders": "Нет заказов за 28 дней",
        "no_sales": "Нет продаж за 28 дней",
        "loading": "Загружается",
        "no_data": "Нет данных",
    }[position.turnover_status]
    row.extend([number(position.turnover_days), status, currency])
    return row


@router.get(
    "/export",
    operation_id="inventoryOverviewExport",
    response_class=Response,
    responses={200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
)
def export_inventory(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    coverage_channel: CoverageChannel = CoverageChannel.FBO,
):
    member = require_workspace(db, identity, workspace_id)
    if not allows(member, "inventory.read") or not allows(member, "reports.export"):
        raise HTTPException(403, "Нет доступа к выгрузке остатков.")
    stores = reporting_stores(db, workspace_id, store_id, feature="inventory")
    currency = db.get(Workspace, workspace_id).currency
    can_cost = allows(member, "profit.read")
    report = overview(
        db,
        request.app.state.vault,
        workspace_id,
        stores,
        currency,
        can_cost,
        limit=50000,
        coverage_channel=coverage_channel,
    )
    if report.count > 50000:
        raise HTTPException(422, "Для выгрузки более 50 000 товаров выберите один кабинет.")
    headers = [
        "Кабинет",
        "Площадка",
        "Артикул продавца",
        "Артикул площадки",
        "Товар",
        "Цвета",
        "Размеры",
        "Штрихкоды",
        "FBO, шт.",
        "FBO по цене продавца",
        "FBS, шт.",
        "FBS по цене продавца",
    ]
    if can_cost:
        headers.extend(["FBO по себестоимости", "FBS по себестоимости", "Себестоимость полная"])
    headers.extend([f"Запас {coverage_channel.value.upper()}, дней", "Состояние запаса", "Валюта"])
    rows = [position_row(p, currency, can_cost) for p in report.items]
    sheets = [
        (name, headers, [row for row in rows if row[1] == name])
        for name in ("WB", "Ozon")
        if any(row[1] == name for row in rows)
    ]
    summary_headers = [
        "Кабинет",
        "Площадка",
        "FBO, шт.",
        "FBO по цене продавца",
        "FBS, шт.",
        "FBS по цене продавца",
    ]

    def totals(data, title, marketplace):
        result = [
            title,
            marketplace,
            data.fbo.units,
            number(data.fbo.retail_value),
            data.fbs.units,
            number(data.fbs.retail_value),
        ]
        if can_cost:
            result.extend([number(data.fbo.cost_value), number(data.fbs.cost_value)])
        return [*result, currency]

    if can_cost:
        summary_headers.extend(["FBO по себестоимости", "FBS по себестоимости"])
    summary_headers.append("Валюта")
    summaries = [totals(report, "Все выбранные кабинеты", "WB / Ozon")]
    for store in stores:
        child = overview(
            db,
            request.app.state.vault,
            workspace_id,
            [store],
            currency,
            can_cost,
            coverage_channel=coverage_channel,
        )
        summaries.append(totals(child, store.name, "Ozon" if store.marketplace == "ozon" else "WB"))
    sheets.insert(0, ("Сводка", summary_headers, summaries))
    payload = build_template(
        headers, rows, sheet_name="Общие остатки", numeric=True, extra_sheets=sheets
    )
    return Response(
        payload,
        media_type=XLSX,
        headers={
            "Content-Disposition": 'attachment; filename="perk-inventory.xlsx"',
            "Cache-Control": "no-store",
        },
    )
