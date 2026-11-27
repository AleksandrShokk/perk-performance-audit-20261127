import json
from decimal import Decimal

import pytest

from app.integrations.wildberries.data import FINANCE_FIELDS, Source, WBError
from app.main import create_app
from app.modules.sync.normalize import normalize
from app.modules.sync.schemas import FinanceItem


def report_row():
    return {
        "rrdId": 1,
        "reportId": 2,
        "nmId": 0,  # A store-wide charge must survive even without a product.
        "docTypeName": "Продажа",
        "sellerOperName": "Коррекция логистики",
        "quantity": 0,
        "rrDate": "2026-10-01",
        "currency": "RUB",
        "retailAmount": "0",
        "forPay": "0",
        "acquiringFee": "0",
    }


def test_financial_corrections_keep_sign_precision_and_sku_absence():
    _, value = normalize(
        Source.FINANCE,
        {
            **report_row(),
            "deliveryService": Decimal("-1234567.89123"),
            "paidStorage": "0.00",
            "paidAcceptance": None,
            "penalty": "17.20",
            "vendorCode": "SKU-42",
            "sku": "000123",
            "orderDt": "2026-09-25",
            "saleDt": "2026-09-29",
            "srid": "synthetic-sale",
            "buyerPhone": "PRIVATE",
            "ppvzSupplierInn": "PRIVATE",
            "token": "PRIVATE",
        },
    )
    assert value["nm_id"] == "0"
    assert value["delivery_service"] == "-1234567.89123"
    assert value["paid_storage"] == "0.00"
    assert value["paid_acceptance"] is None
    assert value["barcode"] == "000123"
    assert value["order_date"] != value["sale_date"] != value["report_date"]
    assert "PRIVATE" not in json.dumps(value)
    output = FinanceItem.model_validate(value).model_dump()
    assert output["data_version"] == 3
    assert not output["requested_amounts_complete"]
    assert "paid_acceptance" in output["missing_amount_fields"]
    assert "paid_storage" not in output["missing_amount_fields"]


@pytest.mark.parametrize(
    "amount", ["NaN", "Infinity", "-Infinity", "1e16", "0.0000000000000000000000001", {}]
)
def test_invalid_new_expense_fields_are_rejected_without_values_in_error(amount):
    with pytest.raises(WBError, match="^wb_invalid_record$"):
        normalize(Source.FINANCE, {**report_row(), "paidStorage": amount})


def test_old_report_rows_remain_readable_with_unknown_expenses():
    _, value = normalize(Source.FINANCE, report_row())
    old = {
        key: value[key]
        for key in (
            "rrd_id",
            "report_id",
            "nm_id",
            "document_type",
            "operation",
            "quantity",
            "report_date",
            "currency",
            "retail_amount",
            "for_pay",
            "acquiring_fee",
        )
    }
    output = FinanceItem.model_validate(old).model_dump()
    assert output["data_version"] == 1
    assert output["delivery_service"] is None
    assert output["sales_commission"] is None
    assert "sales_commission" in output["missing_amount_fields"]
    assert not output["requested_amounts_complete"]


def test_explicit_zeroes_are_known_but_not_proof_of_profit():
    row = report_row()
    # The transport requests only source facts; synthetic explicit zeros model
    # a completely populated row. No cost or profit is inferred from absence.
    for field in FINANCE_FIELDS:
        if field not in row:
            row[field] = "0"
    _, value = normalize(Source.FINANCE, row)
    output = FinanceItem.model_validate(value).model_dump()
    assert output["missing_amount_fields"] == []
    assert output["requested_amounts_complete"]
    assert "profit" not in output


def test_financial_contract_exposes_nullable_expenses_and_readonly_quality():
    schemas = create_app().openapi()["components"]["schemas"]
    properties = schemas["FinanceItem"]["properties"]
    assert {"type": "null"} in properties["paid_storage"]["anyOf"]
    assert properties["data_version"]["default"] == 1
    assert properties["missing_amount_fields"]["readOnly"]
    assert properties["requested_amounts_complete"]["readOnly"]
    assert "ppvzSupplierInn" not in FINANCE_FIELDS
    assert "acquiringBank" not in FINANCE_FIELDS


@pytest.mark.parametrize("value", ["12.1234567890123456789", "-0.123456789012345678901234"])
def test_wb_long_decimal_amount_is_preserved_without_rounding(value):
    _, row = normalize(Source.FINANCE, {**report_row(), "vw": value})
    assert row["wb_remuneration"] == value
    assert FinanceItem.model_validate(row).wb_remuneration == value


def test_financial_precision_preserves_large_totals_and_restores_callers_context():
    from decimal import getcontext, localcontext

    from app.modules.finance.precision import money_precision

    @money_precision()
    def total():
        return Decimal("9999999999999999.999999999999999999999999") + Decimal(
            "0.000000000000000000000001"
        )

    with localcontext() as context:
        context.prec = 28
        assert format(total(), "f") == "10000000000000000.000000000000000000000000"
        assert getcontext().prec == 28
