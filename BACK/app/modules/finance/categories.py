"""Financial report details. Each WB charge belongs to exactly one category.

These facts explain the payout calculation; included fees and compensation are
never subtracted/added a second time. Unrecognised descriptions remain visible.
"""

from collections import defaultdict
from decimal import Decimal

from app.modules.finance.precision import money_precision

DEDUCTION_CATEGORIES = ("advertising", "jam", "showcase", "payout_service", "other")
EXTERNAL_CATEGORIES = (
    "packaging",
    "fulfillment",
    "transport",
    "advertising",
    "rent",
    "salary",
    "other",
)
DETAIL_FIELDS = (
    "seller_sales",
    "seller_returns",
    "seller_revenue",
    "customer_payout",
    "payout_corrections",
    "acquiring",
    "acquiring_corrections",
    "commission",
    "fees_total",
    "wb_expenses_total",
    "total_expenses",
    "logistics_forward",
    "logistics_reverse",
    "logistics_other",
    "compensation_defect",
    "compensation_damage",
    "compensations_total",
    "loyalty_points",
    "loyalty_cost",
    "loyalty_compensation",
    "unclassified_deduction_rows",
    "missing_acquiring_rows",
    "missing_cost_skus",
    *("deduction_" + key for key in DEDUCTION_CATEGORIES),
    *("external_" + key for key in EXTERNAL_CATEGORIES),
)

DEFECT_OPERATIONS = frozenset(
    {
        "компенсация брака",
        "оплата брака",
        "частичная компенсация брака",
        "добровольная компенсация при возврате",
    }
)
DAMAGE_OPERATIONS = frozenset(
    {
        "оплата потерянного товара",
        "компенсация потерянного товара",
        "авансовая оплата за товар без движения",
        "компенсация подмененного товара",
        "компенсация подмен",
        "компенсация ущерба",
        "компенсация подмена",
    }
)
ACQUIRING_CORRECTIONS = frozenset({"корректировка эквайринга"})
SERVICE_OPERATIONS = frozenset(
    {
        "доставка",
        "хранение",
        "платная приемка",
        "приемка",
        "штраф",
        "удержание",
        "коррекция логистики",
        "корректировка логистики",
        "возмещение издержек по перемещению и операционной обработке товара",
        "возмещение издержек по перевозке/по складским операциям с товаром",
        "возмещение за выдачу и возврат товаров на пвз",
        "компенсация скидки по программе лояльности",
        "стоимость участия в программе лояльности",
    }
)


def text(value):
    return " ".join((value or "").casefold().replace("ё", "е").split())


def compensation_kind(operation):
    operation = text(operation)
    if operation in DEFECT_OPERATIONS:
        return "defect"
    if operation in DAMAGE_OPERATIONS:
        return "damage"
    return None


def payout_correction(row):
    """Zero-turnover corrections adjust a payout, never inventory or customer quantities."""
    return (
        text(row.get("operation")) in {"коррекция продаж", "коррекция возвратов"}
        and text(row.get("document_type")) in {"продажа", "возврат"}
        and all(
            row.get(field) is not None and Decimal(row[field]) == 0
            for field in ("retail_amount", "retail_price_with_discount")
        )
    )


def reviewed_service(row):
    operation = text(row.get("operation"))
    if payout_correction(row):
        return True
    if compensation_kind(operation) or operation in ACQUIRING_CORRECTIONS:
        return text(row.get("document_type")) in {"продажа", "возврат"}
    service = operation in SERVICE_OPERATIONS or operation.startswith("сумма баллов, удержанных")
    # Separate informational service rows cannot invent customer turnover or payouts.
    return (
        service
        and row.get("retail_amount") is not None
        and row.get("for_pay") is not None
        and (Decimal(row["retail_amount"]) == 0 and Decimal(row["for_pay"]) == 0)
    )


def deduction_category(description):
    # Only the service title is used. Campaign IDs, dates and account data are not retained here.
    title = text(description).split(",", 1)[0]
    if "wb продвижение" in title:
        return "advertising"
    if "джем" in title:
        return "jam"
    if "витрина" in title:
        return "showcase"
    if "срок" in title and ("перечислен" in title or "выплат" in title):
        return "payout_service"
    return "other"


@money_precision()
def detail_facts(row, customer):
    values = defaultdict(Decimal)
    document = text(row.get("document_type"))
    sign = -1 if document == "возврат" else 1
    operation = text(row.get("operation"))
    payout = row.get("for_pay")
    if customer:
        kind, quantity = customer
        signed = -1 if kind == "returns" else 1
        price = row.get("retail_price_with_discount")
        if price is None:
            values["detail_missing_seller_price"] = 1
        else:
            amount = abs(Decimal(price)) * quantity
            values["detail_seller_" + kind] = amount
            values["detail_seller_revenue"] = amount * signed
        if payout is not None:
            values["detail_customer_payout"] = abs(Decimal(payout)) * signed
        fee = row.get("acquiring_fee")
        percent = row.get("acquiring_percent")
        if fee is None or (Decimal(fee) and percent is None):
            values["detail_missing_acquiring"] = 1
        elif percent is None or Decimal(percent) > 0:
            values["detail_acquiring"] = Decimal(fee) * signed
    if payout_correction(row) and payout is not None:
        values["detail_payout_corrections"] = -abs(Decimal(payout)) if sign < 0 else Decimal(payout)
    compensation = compensation_kind(operation)
    if compensation and payout is not None:
        values["detail_compensation_" + compensation] = (
            -abs(Decimal(payout)) if sign < 0 else Decimal(payout)
        )
    if operation in ACQUIRING_CORRECTIONS and payout is not None:
        values["detail_acquiring_corrections"] = (
            -abs(Decimal(payout)) if sign < 0 else Decimal(payout)
        )
    deduction = row.get("deduction")
    if deduction is not None:
        category = deduction_category(row.get("bonus_type_name"))
        values["detail_deduction_" + category] = Decimal(deduction)
        if Decimal(deduction) and not row.get("bonus_type_name"):
            values["detail_missing_deduction_description"] = 1
    logistics = row.get("delivery_service")
    if logistics is not None:
        description = text(row.get("bonus_type_name"))
        direction = (
            "reverse"
            if "от клиента" in description
            else "forward"
            if "к клиенту" in description
            else "other"
        )
        values["detail_logistics_" + direction] = Decimal(logistics)
    for key, field in (
        ("loyalty_points", "cashback_amount"),
        ("loyalty_cost", "cashback_commission_change"),
        ("loyalty_compensation", "cashback_discount"),
    ):
        amount = row.get(field)
        if amount is None:
            values["detail_missing_" + key] = 1
        else:
            values["detail_" + key] = -abs(Decimal(amount)) if sign < 0 else Decimal(amount)
    return dict(values)


@money_precision()
def render_details(values, settlement, cogs, external):
    if not values["records"]:
        return {field: None for field in DETAIL_FIELDS}
    result = {field: values.get("detail_" + field, Decimal(0)) for field in DETAIL_FIELDS}
    result["seller_revenue"] = (
        None if values["detail_missing_seller_price"] else result["seller_revenue"]
    )
    if values["detail_missing_acquiring"]:
        result["acquiring"] = None
    seller, acquiring = result["seller_revenue"], result["acquiring"]
    result["commission"] = (
        None
        if seller is None or acquiring is None or values["missing_for_pay"]
        else (seller - result["customer_payout"] - acquiring - result["payout_corrections"])
    )
    # The combined deduction is known even when an old report cannot split the bank fee.
    # Payout and acquiring corrections are already included in for_pay: count them once.
    result["fees_total"] = (
        None
        if seller is None or values["missing_for_pay"]
        else seller
        - result["customer_payout"]
        - result["payout_corrections"]
        - result["acquiring_corrections"]
    )
    if acquiring is not None:
        result["acquiring"] = acquiring - result["acquiring_corrections"]
    result["compensations_total"] = result["compensation_defect"] + result["compensation_damage"]
    result["wb_expenses_total"] = (
        None
        if seller is None or settlement is None
        else seller + result["compensations_total"] - settlement
    )
    result["total_expenses"] = (
        None
        if result["wb_expenses_total"] is None or cogs is None
        else result["wb_expenses_total"] + cogs + external
    )
    for key in ("loyalty_points", "loyalty_cost", "loyalty_compensation"):
        if values["detail_missing_" + key]:
            result[key] = None
    result["unclassified_deduction_rows"] = values["detail_missing_deduction_description"]
    result["missing_acquiring_rows"] = values["detail_missing_acquiring"]
    # A unique SKU count is attached only to a complete published summary by the reader.
    result["missing_cost_skus"] = None
    if values["detail_missing_deduction_description"]:
        # Known unclassified money stays in Other, while unprovable split values stay unknown.
        for key in DEDUCTION_CATEGORIES:
            if key != "other" and result["deduction_" + key] == 0:
                result["deduction_" + key] = None
    return {key: format(value, "f") if value is not None else None for key, value in result.items()}
