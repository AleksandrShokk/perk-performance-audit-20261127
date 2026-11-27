"""Exact identifiers only; FBO SKUs are read from the native Ozon channel map."""

import hashlib
import json
from collections import Counter

from fastapi import HTTPException

from app.modules.catalog.ozon_read import snapshot
from app.modules.supplies.template_schemas import TemplateChoice, TemplatePosition

LABELS = {"barcode": "Штрихкод", "vendor_code": "Артикул продавца", "fbo_sku": "SKU Ozon FBO"}
MAX_POSITIONS = 10000


def fbo_skus(db, vault, store):
    rows, _ = snapshot(db, vault, store.workspace_id, store)
    ownership = Counter(
        sku for row in rows or [] for sku in set(row.get("channel_skus", {}).get("fbo", []))
    )
    return {
        row["external_id"]: skus[0]
        for row in rows or []
        if len(skus := list(set(row.get("channel_skus", {}).get("fbo", [])))) == 1
        and ownership[skus[0]] == 1
    }


def positions(plan, kind, skus):
    if kind != "barcode" and plan.marketplace != "ozon":
        raise HTTPException(422, "Для WB используйте штрихкод размера.")
    result, used = [], set()
    for item in plan.items:
        if sum(v.quantity for v in item.variants) != item.quantity:
            raise HTTPException(
                409, "Сначала распределите количество по размерам и сохраните план."
            )
        for variant in item.variants:
            if not variant.quantity:
                continue
            value = {
                "barcode": variant.barcode,
                "vendor_code": item.vendor_code,
                "fbo_sku": skus.get(variant.external_id, ""),
            }[kind]
            if not value or (kind == "barcode" and value not in variant.barcodes):
                raise HTTPException(
                    409,
                    f"Нет однозначного идентификатора «{LABELS[kind]}»: "
                    f"{item.vendor_code or item.nm_id}.",
                )
            if value in used:
                raise HTTPException(
                    409, "Один идентификатор относится к нескольким позициям. Выберите другой тип."
                )
            used.add(value)
            result.append(TemplatePosition(identifier=value, quantity=variant.quantity))
    if not result or len(result) > MAX_POSITIONS:
        raise HTTPException(409, "Выгрузка должна содержать от 1 до 10000 позиций.")
    return result


def digest(rows):
    payload = json.dumps(
        [(row.identifier, row.quantity) for row in rows], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def choices(plan, skus):
    result = []
    for kind in LABELS if plan.marketplace == "ozon" else ["barcode"]:
        try:
            rows = positions(plan, kind, skus)
            result.append(
                TemplateChoice(
                    value=kind,
                    label=LABELS[kind],
                    count=len(rows),
                    units=sum(r.quantity for r in rows),
                    data_digest=digest(rows),
                    error=None,
                    preview=rows[:3],
                )
            )
        except HTTPException as exc:
            result.append(
                TemplateChoice(
                    value=kind,
                    label=LABELS[kind],
                    count=0,
                    units=0,
                    data_digest="",
                    error=str(exc.detail),
                    preview=[],
                )
            )
    return result
