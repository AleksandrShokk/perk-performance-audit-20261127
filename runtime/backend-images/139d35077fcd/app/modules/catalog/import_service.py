"""Review/apply imports against native listing and variant identities in one company."""

import json
from collections import defaultdict
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.modules.accounts.models import Store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.auth.dependencies import now
from app.modules.catalog.import_schemas import (
    CatalogImportError,
    CatalogImportLine,
    CatalogImportResult,
)
from app.modules.catalog.match_models import CatalogImportPreview, ProductMatch
from app.modules.catalog.service import products
from app.modules.supplies.models import SupplyPackaging

PACKAGING_HEADERS = ("Артикул продавца", "Баркод (необязательно)", "В коробе, шт.")
MATCH_HEADERS = (
    "Артикул продавца WB",
    "Баркод WB",
    "Артикул продавца Ozon",
    "Баркод Ozon",
)


def import_aad(wid, sid, uid, pid, kind):
    return f"perk-catalog-import:v1:{wid}:{sid}:{uid}:{pid}:{kind}"


def match_aad(wid, mid):
    return f"perk-catalog-match:v1:{wid}:{mid}"


def catalog(db, vault, wid, store):
    result = products(db, vault, wid, [store], "RUB", "", False, False, False, False, None, 0)
    if len(result.items) > 20000:
        raise HTTPException(422, "В кабинете слишком много товаров для одного импорта.")
    return result.items


def pair(db, identity, wid, left, right):
    require_workspace(db, identity, wid, owner=True)
    a, b = find_store(db, wid, left), find_store(db, wid, right)
    if a.marketplace != "wildberries" or b.marketplace != "ozon":
        raise HTTPException(422, "Выберите кабинет WB и кабинет Ozon.")
    return a, b


def variant_index(cards):
    return {variant.id: (card, variant) for card in cards for variant in card.variants}


def resolve(cards, article, barcode=""):
    found = [
        (card, variant)
        for card in cards
        if card.vendor_code == article.strip()
        for variant in card.variants
        if not barcode or barcode.strip() in variant.barcodes
    ]
    if len(found) != 1:
        raise ValueError(
            "Укажите баркод нужного размера."
            if found
            else "Артикул или баркод не найден в выбранном кабинете."
        )
    return found[0]


def packaging_rows(cards, rows):
    result, errors, seen = [], [], set()
    for number, cells in rows:
        try:
            found = [
                card
                for card in cards
                if card.vendor_code == cells[0].strip()
                and (not cells[1] or any(cells[1] in v.barcodes for v in card.variants))
            ]
            if len(found) != 1:
                raise ValueError("Артикул не найден или неоднозначен. Уточните баркод.")
            multiple = int(cells[2])
            if str(multiple) != cells[2].strip() or not 1 <= multiple <= 10000:
                raise ValueError("Вложимость — целое число от 1 до 10000.")
            if found[0].id in seen:
                raise ValueError("Товар повторяется в файле.")
            seen.add(found[0].id)
            result.append(
                CatalogImportLine(
                    row=number,
                    product_id=found[0].id,
                    vendor_code=found[0].vendor_code,
                    barcode=cells[1],
                    box_multiple=multiple,
                )
            )
        except (ValueError, IndexError) as exc:
            errors.append(CatalogImportError(row=number, message=str(exc)))
    return result, errors


def manual_matches(left, right, rows):
    result, errors, used_left, used_right = [], [], set(), set()
    for number, cells in rows:
        try:
            a, av = resolve(left, cells[0], cells[1])
            b, bv = resolve(right, cells[2], cells[3])
            if av.id in used_left or bv.id in used_right:
                raise ValueError("Вариант повторяется в нескольких соответствиях.")
            used_left.add(av.id)
            used_right.add(bv.id)
            result.append(
                CatalogImportLine(
                    row=number,
                    vendor_code=a.vendor_code,
                    barcode=cells[1] or next(iter(av.barcodes), ""),
                    left_variant_id=av.id,
                    right_variant_id=bv.id,
                    right_vendor_code=b.vendor_code,
                    right_barcode=cells[3] or next(iter(bv.barcodes), ""),
                )
            )
        except (ValueError, IndexError) as exc:
            errors.append(CatalogImportError(row=number, message=str(exc)))
    return result, errors


def automatic_matches(left, right):
    indexes = []
    for cards in (left, right):
        index = defaultdict(set)
        for card in cards:
            for variant in card.variants:
                for barcode in variant.barcodes:
                    if barcode:
                        index[barcode].add(variant.id)
        indexes.append(index)
    proposals, ambiguous = defaultdict(set), set()
    for barcode in indexes[0].keys() & indexes[1].keys():
        a, b = indexes[0][barcode], indexes[1][barcode]
        if len(a) != 1 or len(b) != 1:
            ambiguous.update(a)
            continue
        proposals[next(iter(a))].add((next(iter(b)), barcode))
    reverse = defaultdict(set)
    for aid, candidates in proposals.items():
        for bid, _ in candidates:
            reverse[bid].add(aid)
    left_index, right_index = variant_index(left), variant_index(right)
    result, errors = [], []
    for aid, candidates in sorted(proposals.items()):
        targets = {bid for bid, _ in candidates}
        if aid in ambiguous or len(targets) != 1 or any(len(reverse[bid]) != 1 for bid in targets):
            errors.append(
                CatalogImportError(
                    row=0,
                    message="Неоднозначный штрихкод: " + left_index[aid][0].vendor_code,
                )
            )
            continue
        bid, barcode = min(candidates)
        result.append(
            CatalogImportLine(
                row=len(result) + 1,
                vendor_code=left_index[aid][0].vendor_code,
                barcode=barcode,
                left_variant_id=aid,
                right_variant_id=bid,
                right_vendor_code=right_index[bid][0].vendor_code,
                right_barcode=barcode,
            )
        )
    # Ambiguous matches are excluded; unambiguous matches can still be reviewed.
    return result, errors


def check_existing(db, wid, left, right, rows):
    existing = db.scalars(
        select(ProductMatch).where(
            ProductMatch.workspace_id == wid,
            ProductMatch.left_store_id == left,
            ProductMatch.right_store_id == right,
        )
    ).all()
    a = {str(row.left_variant_id): str(row.right_variant_id) for row in existing}
    b = {str(row.right_variant_id): str(row.left_variant_id) for row in existing}
    return [
        CatalogImportError(
            row=row.row,
            message="У варианта уже есть другое соответствие. Сначала удалите его.",
        )
        for row in rows
        if (row.left_variant_id in a and a[row.left_variant_id] != row.right_variant_id)
        or (row.right_variant_id in b and b[row.right_variant_id] != row.left_variant_id)
    ]


def preview(
    db,
    vault,
    wid,
    sid,
    uid,
    kind,
    rows,
    errors,
    *,
    right_store_id=None,
    source="manual",
):
    if not rows and not errors:
        errors = [CatalogImportError(row=0, message="Подходящих строк нет.")]
    pid = None
    if rows and (not errors or source == "barcode"):
        db.execute(
            delete(CatalogImportPreview).where(
                CatalogImportPreview.workspace_id == wid,
                CatalogImportPreview.expires_at < now(),
            )
        )
        count = db.scalars(
            select(CatalogImportPreview.id)
            .where(
                CatalogImportPreview.workspace_id == wid,
                CatalogImportPreview.created_by == uid,
                CatalogImportPreview.consumed_at.is_(None),
            )
            .limit(20)
        ).all()
        if len(count) >= 20:
            raise HTTPException(429, "Закройте прежние импорты или повторите через 30 минут.")
        pid = uuid4()
        data = {
            "rows": [row.model_dump() for row in rows],
            "right_store_id": str(right_store_id) if right_store_id else None,
            "source": source,
        }
        db.add(
            CatalogImportPreview(
                workspace_id=wid,
                id=pid,
                store_id=sid,
                created_by=uid,
                kind=kind,
                ciphertext=vault.seal(json.dumps(data), import_aad(wid, sid, uid, pid, kind)),
                expires_at=now() + timedelta(minutes=30),
            )
        )
    return CatalogImportResult(
        preview_id=pid,
        rows_count=len(rows) + len(errors),
        valid_count=len(rows),
        errors=errors[:100],
        items=rows[:100],
        can_apply=pid is not None,
    )


def apply(db, vault, wid, sid, uid, pid, kind, identity, *, right_store_id=None):
    require_workspace(db, identity, wid, owner=True)
    saved = db.get(CatalogImportPreview, (wid, pid), with_for_update=True)
    if (
        not saved
        or saved.store_id != sid
        or saved.created_by != uid
        or saved.kind != kind
        or saved.expires_at <= now()
    ):
        raise HTTPException(404, "Предпросмотр истёк. Загрузите файл ещё раз.")
    payload = json.loads(vault.open(saved.ciphertext, import_aad(wid, sid, uid, pid, kind)))
    if kind == "matching" and str(right_store_id) != payload["right_store_id"]:
        raise HTTPException(409, "Кабинеты изменились. Повторите предпросмотр.")
    rows = [CatalogImportLine.model_validate(row) for row in payload["rows"]]
    if saved.consumed_at:
        return len(rows)
    store = find_store(db, wid, sid)
    current = catalog(db, vault, wid, store)
    if kind == "packaging":
        indexed = {card.id: card for card in current}
        if any(
            row.product_id not in indexed
            or (
                row.barcode
                and not any(
                    row.barcode in variant.barcodes for variant in indexed[row.product_id].variants
                )
            )
            for row in rows
        ):
            raise HTTPException(409, "Каталог изменился. Повторите предпросмотр.")
        for row in rows:
            statement = insert(SupplyPackaging).values(
                workspace_id=wid,
                store_id=sid,
                product_key=indexed[row.product_id].nm_id
                if store.marketplace == "wildberries"
                else row.product_id,
                box_multiple=row.box_multiple,
                updated_by=uid,
                updated_at=now(),
            )
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["workspace_id", "store_id", "product_key"],
                    set_={
                        "box_multiple": row.box_multiple,
                        "updated_by": uid,
                        "updated_at": now(),
                    },
                )
            )
    else:
        right = UUID(payload["right_store_id"])
        # Serialize imports for the pair, including imports from separate previews.
        db.scalars(
            select(Store)
            .where(Store.workspace_id == wid, Store.id.in_([sid, right]))
            .order_by(Store.id)
            .with_for_update()
        ).all()
        _a, b = pair(db, identity, wid, sid, right)
        left_index = variant_index(current)
        right_index = variant_index(catalog(db, vault, wid, b))
        if any(
            row.left_variant_id not in left_index
            or row.right_variant_id not in right_index
            or (row.barcode and row.barcode not in left_index[row.left_variant_id][1].barcodes)
            or (
                row.right_barcode
                and row.right_barcode not in right_index[row.right_variant_id][1].barcodes
            )
            for row in rows
        ):
            raise HTTPException(409, "Варианты изменились. Повторите предпросмотр.")
        if check_existing(db, wid, sid, right, rows):
            raise HTTPException(409, "Соответствия изменились. Повторите предпросмотр.")
        for row in rows:
            existing = db.scalar(
                select(ProductMatch).where(
                    ProductMatch.workspace_id == wid,
                    ProductMatch.left_store_id == sid,
                    ProductMatch.right_store_id == right,
                    ProductMatch.left_variant_id == UUID(row.left_variant_id),
                )
            )
            if existing:
                continue
            mid = uuid4()
            data = {
                "left_vendor_code": row.vendor_code,
                "right_vendor_code": row.right_vendor_code,
                "left_barcode": row.barcode,
                "right_barcode": row.right_barcode,
                "source": payload["source"],
            }
            db.add(
                ProductMatch(
                    workspace_id=wid,
                    id=mid,
                    left_store_id=sid,
                    right_store_id=right,
                    left_variant_id=UUID(row.left_variant_id),
                    right_variant_id=UUID(row.right_variant_id),
                    created_by=uid,
                    ciphertext=vault.seal(json.dumps(data), match_aad(wid, mid)),
                )
            )
    saved.consumed_at = now()
    return len(rows)
