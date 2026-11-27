from datetime import date

import pytest
from cost_workbook import TEMPLATE, cost_workbook
from cryptography.exceptions import InvalidTag
from pydantic import ValidationError

from app.modules.finance.schemas import CostInput
from app.modules.finance.service import expense_aad, import_aad, price_aad
from app.modules.finance.xlsx import InvalidWorkbook, read_rows


def test_download_template_is_empty_and_headers_are_readable():
    assert read_rows(TEMPLATE.read_bytes()) == []


def test_excel_serial_dates_and_leading_zero_barcodes():
    serial = (date(2026, 10, 1) - date(1899, 12, 30)).days
    rows = read_rows(cost_workbook([["42", "000123", "120,50", ("n", serial), "RUB"]]))
    assert rows == [(2, ["42", "000123", "120,50", "2026-10-01", "RUB"])]


@pytest.mark.parametrize(
    "extra",
    [
        {"xl/vbaProject.bin": "not a real macro"},
        {"xl/activeX/activeX1.xml": "blocked"},
        {"../outside.xml": "blocked"},
        {"xl/worksheets/large.xml": "A" * (13 * 1024 * 1024)},
        {
            "xl/_rels/external.xml.rels": '<Relationships><Relationship TargetMode="External" '
            'Target="https://example.invalid"/></Relationships>'
        },
    ],
)
def test_active_content_external_links_and_zip_bombs_are_rejected(extra):
    with pytest.raises(InvalidWorkbook):
        read_rows(cost_workbook(extras=extra))


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE sheet [<!ENTITY private SYSTEM "file:///run/secrets/security_config">]>'
        "<worksheet>&private;</worksheet>",
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row><c r="C2"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>',
        "<worksheet><broken>",
    ],
)
def test_dtd_formulas_and_malformed_xml_are_rejected_without_evaluation(xml):
    with pytest.raises(InvalidWorkbook):
        read_rows(cost_workbook(sheet_xml=xml))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0.00001", "100000000000000000"])
def test_invalid_cost_amounts_are_not_silently_rounded(value):
    with pytest.raises(ValidationError):
        CostInput(nm_id="42", amount=value, currency="RUB", effective_from="2026-10-01")


def test_zero_cost_is_distinct_from_missing():
    assert (
        CostInput(nm_id="42", amount="0", currency="RUB", effective_from="2026-10-01").amount == 0
    )
    with pytest.raises(ValidationError):
        CostInput(nm_id="42", amount="", currency="RUB", effective_from="2026-10-01")


def test_encrypted_cost_cannot_be_moved_to_another_variant_date_or_tenant(vault):
    value = CostInput(
        nm_id="42", barcode="0001", amount="100", currency="RUB", effective_from="2026-10-01"
    )
    encrypted = vault.seal("100", price_aad("workspace", "store", value))
    contexts = [
        price_aad("another-workspace", "store", value),
        price_aad("workspace", "another-store", value),
        price_aad("workspace", "store", value.model_copy(update={"barcode": "0002"})),
        price_aad("workspace", "store", value.model_copy(update={"nm_id": "43"})),
        price_aad("workspace", "store", value.model_copy(update={"currency": "USD"})),
        price_aad(
            "workspace", "store", value.model_copy(update={"effective_from": date(2026, 9, 1)})
        ),
        import_aad("workspace", "store", "preview"),
        expense_aad("workspace", "store", "expense"),
    ]
    for context in contexts:
        with pytest.raises(InvalidTag):
            vault.open(encrypted, context)
