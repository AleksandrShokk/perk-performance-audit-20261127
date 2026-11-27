from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_STORED, ZipFile

import pytest
from fastapi import HTTPException

from app.modules.finance.xlsx import build_template
from app.modules.supplies.template_data import positions
from app.modules.supplies.template_schemas import TemplateMapping, TemplatePosition
from app.modules.supplies.template_workbook import NS, InvalidTemplate, Workbook


def template(rows=(), headers=("Баркод", "Количество"), transform=None, extra=None):
    raw = build_template(headers, rows)
    with ZipFile(BytesIO(raw)) as book:
        parts = {name: book.read(name) for name in book.namelist()}
    if transform:
        parts = transform(parts)
    parts.update(extra or {})
    output = BytesIO()
    with ZipFile(output, "w", ZIP_STORED) as book:
        for name, data in parts.items():
            book.writestr(name, data)
    return output.getvalue()


def mapping(**changes):
    return TemplateMapping(
        sheet="Себестоимость",
        header_row=1,
        first_row=2,
        identifier_column="A",
        quantity_column="B",
        identifier_type="barcode",
        mode="append",
        **changes,
    )


def values(raw):
    book = Workbook(raw)
    try:
        _, _, _, grid = book.grid("Себестоимость")
        return {
            number: {column: book.value(cell) for column, cell in row.items()}
            for number, row in grid.items()
        }
    finally:
        book.close()


def test_empty_template_is_filled_with_text_identifiers_and_numeric_quantities():
    raw = template()
    book = Workbook(raw)
    try:
        assert book.inspect()[0].headers[0].columns[0].label == "Баркод"
        result = book.fill(
            mapping(),
            [
                TemplatePosition(identifier="00012345678901234567", quantity=8),
                TemplatePosition(identifier="=literal", quantity=5),
            ],
        )
    finally:
        book.close()
    grid = values(result)
    assert grid[2] == {"A": "00012345678901234567", "B": "8"}
    assert grid[3]["A"] == "=literal"
    book = Workbook(result)
    try:
        _, _, _, cells = book.grid("Себестоимость")
        assert cells[2]["A"].getAttribute("t") == "inlineStr"
        assert cells[2]["B"].getAttribute("t") == "n"
        assert not book.xml(book.sheets["Себестоимость"]).getElementsByTagNameNS(NS, "f")
    finally:
        book.close()


def test_existing_rows_keep_other_columns_and_zero_every_other_position():
    raw = template(
        [("0002", 9, "leave"), ("0001", 2, "keep")], headers=("Баркод", "Количество", "Описание")
    )
    book = Workbook(raw)
    try:
        result = book.fill(
            mapping().model_copy(update={"mode": "match"}),
            [TemplatePosition(identifier="0001", quantity=7)],
        )
    finally:
        book.close()
    grid = values(result)
    assert grid[2] == {"A": "0002", "B": "0", "C": "leave"}
    assert grid[3] == {"A": "0001", "B": "7", "C": "keep"}


def test_original_namespace_prefixes_styles_unknown_extensions_and_other_parts_survive():
    def transform(parts):
        name = "xl/worksheets/sheet1.xml"
        text = (
            parts[name]
            .decode()
            .replace(
                "<worksheet xmlns=",
                '<worksheet xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                'xmlns:x14ac="urn:test" mc:Ignorable="x14ac" xmlns=',
            )
        )
        text = text.replace(
            "<sheetData>",
            '<cols><col min="1" max="2" width="24" customWidth="1"/></cols><sheetData>',
        )
        text = text.replace('r="A2"', 'r="A2" s="1"').replace('r="B2"', 'r="B2" s="1"')
        text = text.replace(
            "</worksheet>",
            '<autoFilter ref="A1:B2"/><extLst><ext uri="test">'
            "<x14ac:note>keep</x14ac:note></ext></extLst></worksheet>",
        )
        parts[name] = text.encode()
        return parts

    raw = template(
        [("", "")],
        transform=transform,
        extra={"docProps/custom.xml": b"<Properties><note>unchanged</note></Properties>"},
    )
    book = Workbook(raw)
    try:
        result = book.fill(
            mapping(),
            [
                TemplatePosition(identifier="0001", quantity=5),
                TemplatePosition(identifier="0002", quantity=6),
            ],
        )
    finally:
        book.close()
    with ZipFile(BytesIO(raw)) as before, ZipFile(BytesIO(result)) as after:
        assert set(before.namelist()) == set(after.namelist())
        for name in before.namelist():
            if name != "xl/worksheets/sheet1.xml":
                assert before.read(name) == after.read(name)
        assert b'mc:Ignorable="x14ac"' in after.read("xl/worksheets/sheet1.xml")
        assert b'xmlns:x14ac="urn:test"' in after.read("xl/worksheets/sheet1.xml")
    book = Workbook(result)
    try:
        doc, _, _, grid = book.grid("Себестоимость")
        assert grid[3]["A"].getAttribute("s") == "1"
        assert doc.getElementsByTagNameNS(NS, "autoFilter")[0].getAttribute("ref") == "A1:B3"
    finally:
        book.close()


@pytest.mark.parametrize(
    "mode,rows,key",
    [
        ("append", [("example", 1)], "0001"),
        ("match", [("0001", 1), ("0001", 2)], "0001"),
        ("match", [("0002", 1)], "0001"),
        ("match", [("0001", "1E999999999")], "0001"),
    ],
)
def test_ambiguous_or_unsafe_table_layouts_are_rejected(mode, rows, key):
    book = Workbook(template(rows))
    try:
        with pytest.raises(InvalidTemplate):
            book.fill(
                mapping().model_copy(update={"mode": mode}),
                [TemplatePosition(identifier=key, quantity=5)],
            )
    finally:
        book.close()


@pytest.mark.parametrize("bad", ["formula", "external", "dtd", "macro", "traversal"])
def test_active_or_malformed_workbooks_are_rejected(bad):
    def transform(parts):
        if bad == "formula":
            parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
                b"<sheetData>", b'<sheetData><row r="2"><c r="A2"><f>HYPERLINK()</f></c></row>'
            )
        if bad == "external":
            parts["xl/_rels/sheet1.xml.rels"] = (
                b'<Relationships><Relationship TargetMode="External" Target="https://example.com"/></Relationships>'
            )
        if bad == "dtd":
            parts["xl/worksheets/sheet1.xml"] = (
                b'<!DOCTYPE worksheet [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                + parts["xl/worksheets/sheet1.xml"]
            )
        if bad == "macro":
            parts["xl/vbaProject.bin"] = b"payload"
        if bad == "traversal":
            parts["../file.xml"] = b"<x/>"
        return parts

    with pytest.raises(InvalidTemplate):
        Workbook(template(transform=transform))


def test_fbo_sku_is_never_substituted_with_the_generic_marketplace_code():
    variant = SimpleNamespace(
        external_id="native-product", quantity=3, barcode="0001", barcodes=["0001"]
    )
    plan = SimpleNamespace(
        marketplace="ozon",
        items=[
            SimpleNamespace(
                quantity=3,
                variants=[variant],
                vendor_code="offer",
                nm_id="",
                marketplace_code="WRONG-FBS",
            )
        ],
    )
    assert positions(plan, "fbo_sku", {"native-product": "12345"})[0].identifier == "12345"
    with pytest.raises(HTTPException):
        positions(plan, "fbo_sku", {})
