"""Editable matching workbooks: original identifiers and a separate sheet of row errors."""

import json
from collections import defaultdict
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from sqlalchemy import select

from app.modules.auth.dependencies import now
from app.modules.catalog.import_service import MATCH_HEADERS, import_aad, variant_index
from app.modules.catalog.match_models import CatalogImportPreview, ProductMatch
from app.modules.finance.xlsx import MAX_ROWS, MAX_UPLOAD, build_template

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def workbook(records):
    errors = [[index, message] for index, (_, message) in enumerate(records, 2) if message]
    return build_template(
        MATCH_HEADERS,
        [cells for cells, _ in records],
        sheet_name="Соответствия",
        extra_sheets=[("Ошибки", ("Строка на листе Соответствия", "Что исправить"), errors)],
    )


def export(records):
    # Every generated part must fit the same upload constraints as the original template.
    parts = []

    def add(chunk):
        payload = workbook(chunk)
        if len(payload) > MAX_UPLOAD or len(chunk) > MAX_ROWS:
            if len(chunk) <= 1:
                raise HTTPException(422, "Строка слишком большая для шаблона.")
            middle = len(chunk) // 2
            add(chunk[:middle])
            add(chunk[middle:])
        else:
            parts.append(payload)

    add(records)
    if len(parts) == 1:
        return parts[0], XLSX, "perk-matches-corrections.xlsx"
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for index, payload in enumerate(parts, 1):
            archive.writestr(f"perk-matches-corrections-{index:03}.xlsx", payload)
    return buffer.getvalue(), "application/zip", "perk-matches-corrections.zip"


def manual(rows, errors):
    messages = defaultdict(list)
    for error in errors:
        messages[error.row].append(error.message)
    # Keep valid rows too: an invalid manual import has not saved any of them yet.
    return [(cells, " ".join(messages[number])) for number, cells in rows]


def unmatched(db, vault, wid, uid, left, right, left_cards, right_cards, preview_id=None):
    pending = []
    if preview_id:
        saved = db.get(CatalogImportPreview, (wid, preview_id))
        if (
            not saved
            or saved.store_id != left
            or saved.created_by != uid
            or saved.kind != "matching"
            or saved.expires_at <= now()
        ):
            raise HTTPException(404, "Предпросмотр истёк. Выполните подбор ещё раз.")
        data = json.loads(
            vault.open(saved.ciphertext, import_aad(wid, left, uid, preview_id, "matching"))
        )
        if data["right_store_id"] != str(right):
            raise HTTPException(409, "Кабинеты изменились. Повторите подбор.")
        pending = data["rows"] if not saved.consumed_at else []
    saved = db.scalars(
        select(ProductMatch).where(
            ProductMatch.workspace_id == wid,
            ProductMatch.left_store_id == left,
            ProductMatch.right_store_id == right,
        )
    ).all()
    used_left = {str(row.left_variant_id) for row in saved}
    used_right = {str(row.right_variant_id) for row in saved}
    records = []
    for row in pending:
        if row["left_variant_id"] in used_left and row["right_variant_id"] in used_right:
            continue
        records.append(
            (
                [
                    row["vendor_code"],
                    row["barcode"],
                    row["right_vendor_code"],
                    row["right_barcode"],
                ],
                "",
            )
        )
        used_left.add(row["left_variant_id"])
        used_right.add(row["right_variant_id"])
    for cards, used, side in (
        (left_cards, used_left, "WB"),
        (right_cards, used_right, "Ozon"),
    ):
        indexed = variant_index(cards)
        for vid, (card, variant) in sorted(
            indexed.items(),
            key=lambda item: (item[1][0].vendor_code, item[1][1].size, item[0]),
        ):
            if vid in used:
                continue
            cells = (
                [card.vendor_code, next(iter(variant.barcodes), ""), "", ""]
                if side == "WB"
                else ["", "", card.vendor_code, next(iter(variant.barcodes), "")]
            )
            records.append(
                (
                    cells,
                    "Заполните обе площадки в одной строке. Строку без пары можно удалить.",
                )
            )
    return records
