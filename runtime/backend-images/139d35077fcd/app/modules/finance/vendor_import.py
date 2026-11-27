"""Resolve seller articles inside the chosen WB store before cost preview."""

from collections import defaultdict
from datetime import datetime

from app.integrations.wildberries.data import Source
from app.modules.finance.schemas import RowError
from app.modules.sync.read import retained


def resolve_rows(db, vault, wid, sid, rows):
    index = defaultdict(list)
    for card in retained(db, vault, wid, sid, Source.CATALOG):
        index[card.get("vendor_code", "").strip()].append(card)
    resolved, errors = [], []
    for number, cells in rows:
        matches = index.get(cells[0].strip(), [])
        if cells[1]:
            matches = [
                card
                for card in matches
                if any(cells[1] in size["barcodes"] for size in card.get("sizes", []))
            ]
        if len(matches) != 1:
            errors.append(
                RowError(
                    row=number,
                    field="vendor_code",
                    code="ambiguous_article" if matches else "unknown_product",
                    message="Артикул продавца повторяется. Укажите баркод размера."
                    if matches
                    else "Артикул продавца не найден в этом кабинете.",
                )
            )
            continue
        values = list(cells)
        values[0] = matches[0]["nm_id"]
        if len(values[3]) == 10 and values[3][2] == ".":
            try:
                values[3] = datetime.strptime(values[3], "%d.%m.%Y").date().isoformat()
            except ValueError:
                pass
        resolved.append((number, values))
    return resolved, errors
