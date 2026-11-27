"""Shared accounting rules for staged previews and published financial reports."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.modules.finance.categories import detail_facts, payout_correction, reviewed_service
from app.modules.finance.precision import money_precision

# WB seller instructions: these columns are separate deductions after forPay.
# https://seller.wildberries.ru/instructions/ru/ru/material/how-to-read-general-financial-report
EXPENSE_FIELDS = (
    "delivery_service",
    "paid_storage",
    "paid_acceptance",
    "penalty",
    "deduction",
    "additional_payment",
    "cashback_amount",
    "cashback_commission_change",
    "payment_schedule",
)
# These need separate reconciliation rules. Never guess a sign or subtract an overlapping field.
UNRECONCILED_FIELDS = ("installment_cofinancing_amount",)
INCLUDED_FIELDS = (
    "sales_commission",
    "acquiring_fee",
    "wb_remuneration",
    "wb_remuneration_vat",
    "pickup_reward",
    "rebill_logistic_cost",
)


def report_sale(row):
    """Count customer sales/returns only. Service and correction rows are separate."""
    if payout_correction(row):
        return None
    operation = row.get("operation", "").strip().casefold()
    document = row.get("document_type", "").strip().casefold()
    kind = {
        "продажа": "sales",
        "сторно возвратов": "sales",
        "корректная продажа": "sales",
        "возврат": "returns",
        "сторно продаж": "returns",
        "корректный возврат": "returns",
        "коррекция возвратов": "returns",
        "коррекция продаж": {"продажа": "sales", "возврат": "returns"}.get(document),
    }.get(operation)
    quantity = row["quantity"]
    expected = "продажа" if kind == "sales" else "возврат"
    if kind and document == expected and quantity > 0:
        return kind, quantity
    return None


def sale_day(row):
    try:
        return date.fromisoformat((row.get("sale_date") or "")[:10]).isoformat()
    except ValueError:
        return ""


def original_sales(rows):
    """An ambiguous/missing SRID or excess return quantity must not recover a guessed cost."""
    sales, returned = {}, defaultdict(int)
    for row in rows:
        reference = row.get("sale_reference")
        kind = report_sale(row)
        if not reference or not kind:
            continue
        if kind[0] == "returns":
            returned[reference] += kind[1]
        else:
            candidate = (row["nm_id"], row.get("barcode") or "", sale_day(row), kind[1])
            sales[reference] = None if reference in sales else candidate
    for reference, quantity in returned.items():
        value = sales.get(reference)
        if value and quantity > value[3]:
            sales[reference] = None
    return sales


@money_precision()
def facts(row, links):
    values = defaultdict(Decimal)
    day = date.fromisoformat(row["report_date"][:10])
    nm_id, barcode, cost_day, kind = row["nm_id"], row.get("barcode") or "", "", "other"
    customer = report_sale(row)
    values["records"] = Decimal(1)
    values["detail_v4_records"] = Decimal(1)
    values.update(detail_facts(row, customer))
    service = reviewed_service(row)
    if customer:
        kind, quantity = customer
        values[kind] = Decimal(quantity)
        cost_day = sale_day(row) if kind == "sales" else ""
        if kind == "returns":
            original = links.get(row.get("sale_reference"))
            if original and original[0] == nm_id and (not barcode or barcode == original[1]):
                barcode, cost_day = original[1], original[2]
        amount = row.get("retail_amount")
        values["retail_amount"] = (
            abs(Decimal(amount)) * (1 if kind == "sales" else -1)
            if amount is not None
            else Decimal(0)
        )
        values["missing_retail_amount"] = Decimal(amount is None)
        if kind == "sales" and amount is not None and Decimal(amount) < 0:
            values["unexpected_customer_amount_sign"] = Decimal(1)
    elif not service and (row.get("quantity", 0) != 0 or Decimal(row.get("for_pay") or "0") != 0):
        # Corrections/compensation/service income need a reviewed rule, not a customer sale count.
        values["unclassified_operation"] = Decimal(1)

    document = row.get("document_type", "").strip().casefold()
    payment = row.get("for_pay")
    if document not in {"продажа", "возврат"} and payment is not None and Decimal(payment) != 0:
        values["unclassified_operation"] = Decimal(1)
    values["for_pay"] = (
        (-abs(Decimal(payment)) if document == "возврат" else Decimal(payment))
        if payment is not None
        else Decimal(0)
    )
    values["missing_for_pay"] = Decimal(payment is None)
    if customer and customer[0] == "sales" and payment is not None and Decimal(payment) < 0:
        values["unexpected_customer_amount_sign"] = Decimal(1)
    for field in EXPENSE_FIELDS + INCLUDED_FIELDS + UNRECONCILED_FIELDS:
        amount = row.get(field)
        values[field] = Decimal(amount) if amount is not None else Decimal(0)
        if field in {"cashback_amount", "cashback_commission_change"} and document == "возврат":
            values[field] = -abs(values[field])
        values["missing_" + field] = Decimal(amount is None)
        if field in EXPENSE_FIELDS:
            if (
                field
                not in {
                    "cashback_amount",
                    "cashback_commission_change",
                    "payment_schedule",
                    "additional_payment",
                }
                and document == "возврат"
                and amount is not None
                and Decimal(amount) > 0
            ):
                values["ambiguous_expense_sign"] = Decimal(1)
        elif field in UNRECONCILED_FIELDS:
            if amount is None or Decimal(amount) != 0:
                values["unreconciled_adjustment"] = Decimal(1)
    # A service quantity/payout can need reconciliation without changing customer revenue.
    # Only an explicit zero retail amount proves that a non-sale row adds no revenue.
    amount = row.get("retail_amount")
    values["unclassified_revenue"] = Decimal(
        not customer and not service and (amount is None or Decimal(amount) != 0)
    )
    values["legacy_records"] = Decimal(row.get("data_version", 1) < 2)
    return (day, row["currency"].strip().upper()), (nm_id, barcode, cost_day, kind), dict(values)
