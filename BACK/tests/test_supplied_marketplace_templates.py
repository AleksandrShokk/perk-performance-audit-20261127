"""Regression against the two empty marketplace templates supplied by the owner."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from app.modules.supplies.template_router import suggest
from app.modules.supplies.template_schemas import TemplatePosition
from app.modules.supplies.template_workbook import NS, Workbook


@pytest.mark.parametrize(
    ("filename", "kind", "quantity_column"),
    [("ozon.xlsx", "vendor_code", "C"), ("wb.xlsx", "barcode", "B")],
)
def test_original_template_fills_without_changing_other_parts(filename, kind, quantity_column):
    raw = (Path(__file__).parent / "fixtures" / "supply_templates" / filename).read_bytes()
    book = Workbook(raw)
    try:
        available = [
            SimpleNamespace(value=value, error=None)
            for value in ["barcode", "vendor_code", "fbo_sku"]
        ]
        mapping = suggest(book, book.inspect(), available)
        assert mapping is not None
        assert (
            mapping.identifier_type,
            mapping.identifier_column,
            mapping.quantity_column,
        ) == (kind, "A", quantity_column)
        assert (mapping.first_row, mapping.mode) == (2, "append")
        rows = [
            TemplatePosition(
                identifier=f"00000000000000000000{i:04}" if kind == "barcode" else f"TEST-{i:04}",
                quantity=i % 13 + 1,
            )
            for i in range(1, 124)
        ]
        filled = book.fill(mapping, rows)
        sheet = book.sheets[mapping.sheet]
    finally:
        book.close()
    with ZipFile(BytesIO(raw)) as source, ZipFile(BytesIO(filled)) as result:
        assert source.namelist() == result.namelist()
        assert all(
            source.read(name) == result.read(name) for name in source.namelist() if name != sheet
        )
        xml = ET.fromstring(result.read(sheet))
        cells = {cell.attrib["r"]: cell for cell in xml.findall(f".//{{{NS}}}c")}
        for number, row in enumerate(rows, 2):
            key, quantity = cells[f"A{number}"], cells[f"{quantity_column}{number}"]
            assert key.attrib["t"] == "inlineStr"
            assert "".join(key.itertext()) == row.identifier
            assert quantity.attrib["t"] == "n"
            assert int(quantity.find(f"{{{NS}}}v").text) == row.quantity
            if kind == "vendor_code":
                optional_name = cells.get(f"B{number}")
                assert optional_name is None or not "".join(optional_name.itertext()).strip()
        assert not xml.findall(f".//{{{NS}}}f")
