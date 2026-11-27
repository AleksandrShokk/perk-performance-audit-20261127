"""Allowlist and validate fields before persistence; money is serialized as decimal strings."""

from datetime import date
from decimal import Decimal, InvalidOperation

from app.integrations.wildberries.data import Source, WBError
from app.modules.catalog.identity import wb_identity
from app.modules.finance.fields import AMOUNT_FIELDS, DATA_VERSION, REFERENCE_FIELDS
from app.modules.finance.precision import MAX_AMOUNT_SCALE


def integer(value, *, signed=False) -> int:
    if type(value) is not int or not -(2**63) < value < 2**63 or (not signed and value < 0):
        raise WBError("wb_invalid_record")
    return value


def string(value, limit=500) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise WBError("wb_invalid_record")
    return value


def money(value) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or number.copy_abs() >= Decimal("1e16")
            or number.as_tuple().exponent < -MAX_AMOUNT_SCALE
        ):
            raise ValueError
        return format(number, "f")
    except ValueError, InvalidOperation:
        raise WBError("wb_invalid_record") from None


def normalize(source: Source, row: dict) -> tuple[str, dict]:
    try:
        if source == Source.BALANCE:
            currency = string(row["currency"], 16)
            if not currency:
                raise WBError("wb_invalid_record")
            return "current", {
                "currency": currency,
                "current": money(row.get("current")),
                "for_withdraw": money(row.get("for_withdraw")),
            }
        if source == Source.CATALOG:
            nm = integer(row["nmID"])
            result = {
                "nm_id": str(nm),
                "vendor_code": string(row.get("vendorCode", "")),
                "title": string(row.get("title", "")),
                "brand": string(row.get("brand", "")),
                "subject": string(row.get("subjectName", "")),
            }
            characteristics = row.get("characteristics") or []
            colors = []
            for item in characteristics[:500]:
                if (
                    isinstance(item, dict)
                    and str(item.get("name", "")).strip().casefold() == "цвет"
                ):
                    values = item.get("value", [])
                    for color in values if isinstance(values, list) else [values]:
                        if isinstance(color, str) and color.strip():
                            colors.append(string(color.strip(), 100))
            result["colors"] = list(dict.fromkeys(colors))
            result.update(wb_identity(row))
            sizes = row.get("sizes", [])
            if not isinstance(sizes, list) or len(sizes) > 1000:
                raise WBError("wb_invalid_record")
            result["sizes"] = [
                {
                    "chrt_id": str(integer(s["chrtID"])),
                    "size": string(s.get("techSize", "")),
                    "barcodes": [string(b, 100) for b in s.get("skus", [])],
                }
                for s in sizes
            ]
            return str(nm), result
        if source == Source.SUPPLIES:
            from app.modules.supplies.normalize import normalize_supply

            return normalize_supply(row)
        if source in {Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS}:
            nm = str(integer(row["nmID"]))
            start = date.fromisoformat(string(row["periodStart"], 10))
            end = date.fromisoformat(string(row["periodEnd"], 10))
            if start > end:
                raise WBError("wb_invalid_record")
            metrics = row["metrics"]
            missing = metrics.get("officeMissingTime")
            missing_hours = None
            if missing is not None:
                days = integer(missing["days"], signed=True)
                hours = integer(missing["hours"], signed=True)
                duration = days * 24 + hours
                # Live WB sometimes returns {days: 0, hours: -4}, even for a
                # "balanced" item. Do not clamp it or discard the entire report.
                if days >= 0 and 0 <= hours < 24 and duration <= ((end - start).days + 1) * 24:
                    missing_hours = duration
            return nm, {
                "nm_id": nm,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "stock": integer(metrics["stockCount"])
                if metrics.get("stockCount") is not None
                else None,
                "orders": integer(metrics["ordersCount"])
                if metrics.get("ordersCount") is not None
                else None,
                "missing_hours": missing_hours,
            }
        if source == Source.PRICES:
            nm = str(integer(row["nmID"]))
            sizes = row["sizes"]
            if not isinstance(sizes, list) or len(sizes) > 1000:
                raise WBError("wb_invalid_record")
            prices = {}
            for size in sizes:
                value = money(size.get("discountedPrice"))
                if value is not None and Decimal(value) < 0:
                    raise WBError("wb_invalid_record")
                chrt = str(integer(size["sizeID"]))
                if chrt in prices:
                    raise WBError("wb_invalid_record")
                prices[chrt] = value
            return nm, {
                "nm_id": nm,
                "currency": string(row.get("currencyIsoCode4217", ""), 16),
                "prices": prices,
            }
        if source in {Source.STOCKS, Source.FBS}:
            nm, chrt = integer(row["nmId"]), integer(row["chrtId"])
            warehouse = integer(row["warehouseId"], signed=True)
            return f"{nm}:{chrt}:{warehouse}", {
                "nm_id": str(nm),
                "chrt_id": str(chrt),
                "warehouse_id": str(warehouse),
                "warehouse_name": string(row["warehouseName"]),
                "quantity": integer(row["quantity"]),
                "in_way_to_client": integer(row["inWayToClient"]),
                "in_way_from_client": integer(row["inWayFromClient"]),
            }
        if source == Source.SALES:
            key = string(row["saleID"], 100)
            if not key or key[0] not in {"S", "R"}:
                raise WBError("wb_invalid_record")
            return key, {
                "sale_id": key,
                "srid": string(row.get("srid") or "", 100),
                "size": string(row.get("techSize") or "", 100),
                "nm_id": str(integer(row["nmId"])),
                "kind": "return" if key.startswith("R") else "sale",
                "date": string(row["date"], 64),
                "last_change_date": string(row["lastChangeDate"], 64),
                "vendor_code": string(row.get("supplierArticle", "")),
                "barcode": string(row.get("barcode", ""), 100),
                "warehouse_name": string(row.get("warehouseName", "")),
                "price_with_discount": money(row.get("priceWithDisc")),
                "finished_price": money(row.get("finishedPrice")),
                "for_pay": money(row.get("forPay")),
                "preliminary": True,
            }
        if source == Source.ORDERS:
            # One row = one ordered unit. srid is WB's stable order id (rid in FBS tasks).
            key = string(row["srid"], 100)
            if not key or type(row["isCancel"]) is not bool:
                raise WBError("wb_invalid_record")
            cancelled = string(row.get("cancelDate") or "", 64)
            return key, {
                "srid": key,
                "nm_id": str(integer(row["nmId"])),
                "date": string(row["date"], 64),
                "last_change_date": string(row["lastChangeDate"], 64),
                "vendor_code": string(row.get("supplierArticle", "")),
                "barcode": string(row.get("barcode", ""), 100),
                "size": string(row.get("techSize", ""), 100),
                "warehouse_name": string(row.get("warehouseName", "")),
                "warehouse_type": string(row.get("warehouseType", ""), 100),
                "region": string(row.get("regionName", "")),
                "total_price": money(row.get("totalPrice")),
                "discount_percent": money(row.get("discountPercent")),
                "spp": money(row.get("spp")),
                "price_with_discount": money(row.get("priceWithDisc")),
                "finished_price": money(row.get("finishedPrice")),
                "is_cancel": row["isCancel"],
                # WB marks "not cancelled" with year 1.
                "cancel_date": None
                if cancelled.startswith("0001-") or not cancelled
                else cancelled,
                "preliminary": True,
            }
        if source == Source.FUNNEL:
            nm, day = integer(row["nmId"]), date.fromisoformat(string(row["day"], 10))
            counts = {
                name: integer(row[field])
                for name, field in (
                    ("open_count", "openCount"),
                    ("cart_count", "cartCount"),
                    ("order_count", "orderCount"),
                    ("buyout_count", "buyoutCount"),
                    ("cancel_count", "cancelCount"),
                    ("wishlist_count", "addToWishlist"),
                )
            }
            return f"{day.isoformat()}:{nm}", {
                "day": day.isoformat(),
                "nm_id": str(nm),
                "vendor_code": string(row.get("vendorCode", "")),
                "currency": string(row["currency"], 16),
                **counts,
                "order_sum": money(row["orderSum"]),
                "buyout_sum": money(row["buyoutSum"]),
                "cancel_sum": money(row["cancelSum"]),
            }
        if source == Source.RETURNS:
            # One item (shkId) of a return order (srid). Marking codes are not kept.
            srid, shk = string(row["srid"], 100), integer(row["shkId"])
            if not srid:
                raise WBError("wb_invalid_record")

            def moment(field):
                value = string(row.get(field) or "", 64)
                return value if value and not value.startswith("0001-") else None

            return f"{srid}:{shk}", {
                "srid": srid,
                "shk_id": str(shk),
                "nm_id": str(integer(row["nmId"])),
                "barcode": string(row.get("sku") or "", 100),
                "size": string(row.get("techSize") or "", 100),
                "subject": string(row.get("subjectName") or ""),
                "brand": string(row.get("brand") or ""),
                "return_type": string(row.get("returnType") or ""),
                "return_status": string(row.get("returnStatus") or ""),
                "return_reason": string(row.get("returnReason") or ""),
                "order_date": moment("orderDt"),
                "ready_at": moment("readyToReturnDt"),
                "completed_at": moment("completedDt"),
                "expires_at": moment("expiredDt"),
                "office_id": str(integer(row["dstOfficeId"], signed=True))
                if row.get("dstOfficeId") is not None
                else None,
                "office_address": string(row.get("dstOfficeAddress") or ""),
            }
        if source == Source.FINANCE:
            key = str(integer(row["rrdId"]))
            return key, {
                "rrd_id": key,
                "report_id": str(integer(row["reportId"])),
                "nm_id": str(integer(row["nmId"])),
                "document_type": string(row.get("docTypeName", "")),
                "operation": string(row.get("sellerOperName", "")),
                "quantity": integer(row["quantity"], signed=True),
                "report_date": string(row["rrDate"], 64),
                "currency": string(row["currency"], 16),
                "data_version": DATA_VERSION,
                **{name: money(row.get(field)) for name, field in AMOUNT_FIELDS.items()},
                **{
                    name: None if row.get(field) is None else string(row[field], limit)
                    for name, (field, limit) in REFERENCE_FIELDS.items()
                },
            }
        raise WBError("unsupported_source")
    except KeyError, TypeError, AttributeError, ValueError:
        raise WBError("wb_invalid_record") from None
