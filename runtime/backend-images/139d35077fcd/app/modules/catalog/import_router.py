import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import select

from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.catalog import import_service as service
from app.modules.catalog.import_schemas import (
    CatalogApplyResult,
    CatalogImportResult,
    MatchPair,
    ProductMatchPage,
    ProductMatchView,
)
from app.modules.catalog.match_models import ProductMatch
from app.modules.finance.xlsx import (
    MAX_UPLOAD,
    InvalidWorkbook,
    build_template,
    read_rows,
)
from app.security.limits import rate_limit

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Catalog imports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def owner(request, db, identity, wid):
    require_workspace(db, identity, wid, owner=True)
    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "catalog-files",
        f"{identity.user.id}:{wid}",
        20,
        60,
    )


def read(file, headers, sheet):
    try:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(422, "Выберите XLSX.")
        return read_rows(file.file.read(MAX_UPLOAD + 1), headers=headers, sheet_name=sheet)
    except InvalidWorkbook as error:
        raise HTTPException(422, str(error)) from None
    finally:
        file.file.close()


def xlsx(headers, filename, sheet):
    return Response(
        build_template(headers, sheet_name=sheet),
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/stores/{store_id}/inventory/packaging/template",
    operation_id="inventoryPackagingTemplate",
    response_class=Response,
    responses={200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
)
def packaging_template(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    owner(request, db, identity, workspace_id)
    find_store(db, workspace_id, store_id)
    return xlsx(service.PACKAGING_HEADERS, "perk-box-multiples", "Вложимость")


@router.post(
    "/stores/{store_id}/inventory/packaging/import/preview",
    operation_id="inventoryPackagingPreview",
    response_model=CatalogImportResult,
)
def packaging_preview(
    workspace_id: UUID,
    store_id: UUID,
    file: Annotated[UploadFile, File()],
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner(request, db, identity, workspace_id)
    store = find_store(db, workspace_id, store_id)
    rows, errors = service.packaging_rows(
        service.catalog(db, request.app.state.vault, workspace_id, store),
        read(file, service.PACKAGING_HEADERS, "Вложимость"),
    )
    result = service.preview(
        db,
        request.app.state.vault,
        workspace_id,
        store_id,
        identity.user.id,
        "packaging",
        rows,
        errors,
    )
    db.commit()
    return result


@router.post(
    "/stores/{store_id}/inventory/packaging/import/{preview_id}/apply",
    operation_id="inventoryPackagingApply",
    response_model=CatalogApplyResult,
)
def packaging_apply(
    workspace_id: UUID,
    store_id: UUID,
    preview_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner(request, db, identity, workspace_id)
    count = service.apply(
        db,
        request.app.state.vault,
        workspace_id,
        store_id,
        identity.user.id,
        preview_id,
        "packaging",
        identity,
    )
    audit(
        db,
        "inventory.packaging_imported",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return CatalogApplyResult(applied=count)


@router.get(
    "/catalog/matches",
    operation_id="catalogMatchesList",
    response_model=ProductMatchPage,
)
def matches(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    left_store_id: UUID,
    right_store_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    service.pair(db, identity, workspace_id, left_store_id, right_store_id)
    rows = db.scalars(
        select(ProductMatch)
        .where(
            ProductMatch.workspace_id == workspace_id,
            ProductMatch.left_store_id == left_store_id,
            ProductMatch.right_store_id == right_store_id,
        )
        .order_by(ProductMatch.id)
        .limit(20001)
    ).all()
    if len(rows) > 20000:
        raise HTTPException(422, "Слишком много соответствий. Выберите кабинеты отдельно.")
    return ProductMatchPage(
        items=[
            ProductMatchView(
                id=row.id,
                left_store_id=row.left_store_id,
                right_store_id=row.right_store_id,
                **json.loads(
                    request.app.state.vault.open(
                        row.ciphertext, service.match_aad(workspace_id, row.id)
                    )
                ),
            )
            for row in rows[offset : offset + limit]
        ],
        count=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/catalog/matches/template",
    operation_id="catalogMatchesTemplate",
    response_class=Response,
    responses={200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
)
def match_template(workspace_id: UUID, request: Request, db: DB, identity: FullIdentity):
    owner(request, db, identity, workspace_id)
    return xlsx(service.MATCH_HEADERS, "perk-wb-ozon-matches", "Соответствия")


@router.post(
    "/catalog/matches/preview",
    operation_id="catalogMatchesPreview",
    response_model=CatalogImportResult,
)
def match_preview(
    workspace_id: UUID,
    left_store_id: UUID,
    right_store_id: UUID,
    file: Annotated[UploadFile, File()],
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner(request, db, identity, workspace_id)
    a, b = service.pair(db, identity, workspace_id, left_store_id, right_store_id)
    vault = request.app.state.vault
    rows, errors = service.manual_matches(
        service.catalog(db, vault, workspace_id, a),
        service.catalog(db, vault, workspace_id, b),
        read(file, service.MATCH_HEADERS, "Соответствия"),
    )
    errors.extend(service.check_existing(db, workspace_id, left_store_id, right_store_id, rows))
    result = service.preview(
        db,
        vault,
        workspace_id,
        left_store_id,
        identity.user.id,
        "matching",
        rows,
        errors,
        right_store_id=right_store_id,
    )
    db.commit()
    return result


@router.post(
    "/catalog/matches/automatic",
    operation_id="catalogMatchesAutomatic",
    response_model=CatalogImportResult,
)
def match_automatic(
    workspace_id: UUID,
    data: MatchPair,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner(request, db, identity, workspace_id)
    a, b = service.pair(db, identity, workspace_id, data.left_store_id, data.right_store_id)
    vault = request.app.state.vault
    rows, errors = service.automatic_matches(
        service.catalog(db, vault, workspace_id, a),
        service.catalog(db, vault, workspace_id, b),
    )
    conflicts = service.check_existing(db, workspace_id, a.id, b.id, rows)
    excluded = {error.row for error in conflicts}
    rows = [row for row in rows if row.row not in excluded]
    errors.extend(conflicts)
    result = service.preview(
        db,
        vault,
        workspace_id,
        a.id,
        identity.user.id,
        "matching",
        rows,
        errors,
        right_store_id=b.id,
        source="barcode",
    )
    db.commit()
    return result


@router.post(
    "/catalog/matches/{preview_id}/apply",
    operation_id="catalogMatchesApply",
    response_model=CatalogApplyResult,
)
def match_apply(
    workspace_id: UUID,
    preview_id: UUID,
    data: MatchPair,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner(request, db, identity, workspace_id)
    service.pair(db, identity, workspace_id, data.left_store_id, data.right_store_id)
    count = service.apply(
        db,
        request.app.state.vault,
        workspace_id,
        data.left_store_id,
        identity.user.id,
        preview_id,
        "matching",
        identity,
        right_store_id=data.right_store_id,
    )
    audit(
        db,
        "catalog.matches_imported",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=data.left_store_id,
    )
    db.commit()
    return CatalogApplyResult(applied=count)


@router.delete(
    "/catalog/matches/{match_id}",
    operation_id="catalogMatchDelete",
    response_model=CatalogApplyResult,
)
def match_delete(
    workspace_id: UUID, match_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    owner(request, db, identity, workspace_id)
    row = db.get(ProductMatch, (workspace_id, match_id))
    if not row:
        raise HTTPException(404, "Соответствие не найдено.")
    db.delete(row)
    audit(
        db,
        "catalog.match_deleted",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=match_id,
    )
    db.commit()
    return CatalogApplyResult(applied=1)


def matching_file(records):
    from app.modules.catalog.match_files import export

    payload, content_type, filename = export(records)
    return Response(
        payload,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/catalog/matches/corrections",
    operation_id="catalogMatchesCorrections",
    response_class=Response,
    responses={
        200: {
            "content": {
                XLSX: {"schema": {"type": "string", "format": "binary"}},
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
def match_corrections(
    workspace_id: UUID,
    left_store_id: UUID,
    right_store_id: UUID,
    file: Annotated[UploadFile, File()],
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    from app.modules.catalog.match_files import manual

    owner(request, db, identity, workspace_id)
    a, b = service.pair(db, identity, workspace_id, left_store_id, right_store_id)
    vault = request.app.state.vault
    original = read(file, service.MATCH_HEADERS, "Соответствия")
    rows, errors = service.manual_matches(
        service.catalog(db, vault, workspace_id, a),
        service.catalog(db, vault, workspace_id, b),
        original,
    )
    errors.extend(service.check_existing(db, workspace_id, a.id, b.id, rows))
    return matching_file(manual(original, errors))


@router.get(
    "/catalog/matches/unmatched",
    operation_id="catalogMatchesUnmatched",
    response_class=Response,
    responses={
        200: {
            "content": {
                XLSX: {"schema": {"type": "string", "format": "binary"}},
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
def match_unmatched(
    workspace_id: UUID,
    left_store_id: UUID,
    right_store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    preview_id: UUID | None = None,
):
    from app.modules.catalog.match_files import unmatched

    owner(request, db, identity, workspace_id)
    a, b = service.pair(db, identity, workspace_id, left_store_id, right_store_id)
    vault = request.app.state.vault
    records = unmatched(
        db,
        vault,
        workspace_id,
        identity.user.id,
        a.id,
        b.id,
        service.catalog(db, vault, workspace_id, a),
        service.catalog(db, vault, workspace_id, b),
        preview_id,
    )
    return matching_file(records)
