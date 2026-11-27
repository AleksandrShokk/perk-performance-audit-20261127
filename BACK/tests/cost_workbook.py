"""Synthetic XLSX inputs for parser and transactional import tests."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.modules.finance.xlsx import HEADERS, LEGACY_HEADERS

TEMPLATE = Path(__file__).parents[1] / "app/modules/finance/assets/cost-template.xlsx"


def cost_workbook(rows=(), *, sheet_xml=None, extras=None, headers=HEADERS):
    xml_rows = []
    for number, values in enumerate([headers, *rows], 1):
        cells = []
        for index, value in enumerate(values):
            if value is None:
                continue
            coordinate = f"{chr(65 + index)}{number}"
            if isinstance(value, tuple):
                cell = f'<c r="{coordinate}"><v>{value[1]}</v></c>'
            else:
                cell = f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            cells.append(cell)
        xml_rows.append(f'<row r="{number}">' + "".join(cells) + "</row>")
    xml = sheet_xml or (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(xml_rows) + "</sheetData></worksheet>"
    )
    output = BytesIO()
    with ZipFile(TEMPLATE) as source, ZipFile(output, "w", ZIP_DEFLATED) as result:
        for item in source.infolist():
            result.writestr(
                item.filename,
                xml if item.filename == "xl/worksheets/sheet1.xml" else source.read(item.filename),
            )
        for key, value in (extras or {}).items():
            result.writestr(key, value)
    return output.getvalue()


def legacy_cost_workbook(rows=(), **kwargs):
    return cost_workbook(rows, headers=LEGACY_HEADERS, **kwargs)
