from typing import Annotated
from uuid import UUID
from xml.parsers.expat import ExpatError

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import ValidationError

from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.finance.xlsx import build_template
from app.modules.supplies import plans, template_data
from app.modules.supplies.plan_router import plan_store
from app.modules.supplies.template_schemas import (
    TemplateFillParams,
    TemplateInspection,
    TemplateMapping,
)
from app.modules.supplies.template_workbook import MAX_UPLOAD, InvalidTemplate, Workbook
from app.security.limits import rate_limit

router = APIRouter(
    prefix="/workspaces/{workspace_id}/inventory/plans/{plan_id}/template",
    tags=["Supply templates"],
)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def source(workspace_id, plan_id, request, db, identity):
    require_workspace(db, identity, workspace_id)
    row = plans.find(db, workspace_id, plan_id)
    store = plan_store(db, workspace_id, row.store_id)
    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "supply-template",
        f"{identity.user.id}:{workspace_id}",
        12,
        60,
    )
    return row, store, plans.view(request.app.state.vault, row, store)


def workbook(file):
    try:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise InvalidTemplate("Выберите файл XLSX.")
        return Workbook(file.file.read(MAX_UPLOAD + 1))
    finally:
        file.file.close()


def suggest(book, sheets, choices):
    kinds = {
        "barcode": {"баркод", "штрихкод", "barcode"},
        "vendor_code": {"артикул", "артикул продавца", "offer_id"},
        "fbo_sku": {"sku", "sku ozon", "ozon sku"},
    }
    quantities = {"количество", "количество, шт.", "кол-во", "в поставку, шт.", "quantity"}
    available = [c.value for c in choices if not c.error]
    for sheet in sheets:
        for header in sheet.headers:
            quantity = [c.key for c in header.columns if c.label.casefold().strip() in quantities]
            if len(quantity) != 1:
                continue
            for kind in available:
                keys = [c.key for c in header.columns if c.label.casefold().strip() in kinds[kind]]
                if len(keys) == 1 and keys[0] != quantity[0]:
                    _, _, _, grid = book.grid(sheet.name)
                    mode = (
                        "match"
                        if any(
                            number > header.row and book.value(cells.get(keys[0]))
                            for number, cells in grid.items()
                        )
                        else "append"
                    )
                    return TemplateMapping(
                        sheet=sheet.name,
                        header_row=header.row,
                        first_row=header.row + 1,
                        identifier_column=keys[0],
                        quantity_column=quantity[0],
                        identifier_type=kind,
                        mode=mode,
                    )
    return None


@router.post("/inspect", response_model=TemplateInspection, operation_id="supplyTemplateInspect")
def inspect_template(
    workspace_id: UUID,
    plan_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    file: Annotated[UploadFile, File()],
):
    book = None
    try:
        _, store, plan = source(workspace_id, plan_id, request, db, identity)
        book = workbook(file)
        sheets = book.inspect()
        choices = template_data.choices(
            plan,
            template_data.fbo_skus(db, request.app.state.vault, store)
            if store.marketplace == "ozon"
            else {},
        )
        return TemplateInspection(
            digest=book.digest,
            revision=plan.revision,
            sheets=sheets,
            choices=choices,
            suggested=suggest(book, sheets, choices),
        )
    except (InvalidTemplate, ValueError, ExpatError) as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        file.file.close()
        if book:
            book.close()


@router.post(
    "/fill",
    operation_id="supplyTemplateFill",
    response_class=Response,
    responses={200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
)
def fill_template(
    workspace_id: UUID,
    plan_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    file: Annotated[UploadFile, File()],
    options: Annotated[TemplateFillParams, Depends()],
):
    book = None
    try:
        row, store, plan = source(workspace_id, plan_id, request, db, identity)
        if row.revision != options.revision:
            raise HTTPException(409, "План изменился. Вернитесь к нему и загрузите шаблон заново.")
        book = workbook(file)
        if book.digest != options.digest:
            raise HTTPException(
                409, "Файл отличается от проверенного шаблона. Загрузите его заново."
            )
        rows = template_data.positions(
            plan,
            options.identifier_type,
            template_data.fbo_skus(db, request.app.state.vault, store)
            if store.marketplace == "ozon"
            else {},
        )
        if template_data.digest(rows) != options.data_digest:
            raise HTTPException(409, "Данные каталога обновились. Загрузите шаблон заново.")
        return Response(
            book.fill(options, rows),
            media_type=XLSX,
            headers={
                "Content-Disposition": f'attachment; filename="perk-{store.marketplace}.xlsx"',
                "Cache-Control": "no-store",
            },
        )
    except (InvalidTemplate, ValidationError, ValueError, ExpatError) as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        file.file.close()
        if book:
            book.close()


@router.get(
    "/blank",
    operation_id="supplyTemplateBlank",
    response_class=Response,
    responses={200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
)
def blank_template(
    workspace_id: UUID, plan_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    _, store, _ = source(workspace_id, plan_id, request, db, identity)
    headers = (
        ("артикул", "имя (необязательно)", "количество")
        if store.marketplace == "ozon"
        else ("Баркод", "Количество")
    )
    return Response(
        build_template(headers=headers, sheet_name="Поставка"),
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="perk-{store.marketplace}-blank.xlsx"',
            "Cache-Control": "no-store",
        },
    )
