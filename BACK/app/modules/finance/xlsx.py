"""Read a bounded XLSX without extracting files, executing formulas or accessing URLs."""

import posixpath
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

MAX_UPLOAD = 256 * 1024
MAX_UNCOMPRESSED = 12 * 1024 * 1024
MAX_ROWS = 5000
HEADERS = (
    "Артикул продавца",
    "Баркод (необязательно)",
    "Себестоимость за единицу",
    "Действует с",
    "Валюта",
)
LEGACY_HEADERS = ("Артикул WB", *HEADERS[1:])
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class InvalidWorkbook(ValueError):
    pass


def read_rows(
    payload: bytes, headers=HEADERS, sheet_name="Себестоимость"
) -> list[tuple[int, list[str]]]:
    if len(payload) > MAX_UPLOAD:
        raise InvalidWorkbook("Слишком большой файл: максимум 256 КБ.")
    try:
        with ZipFile(BytesIO(payload)) as book:
            entries = book.infolist()
            if (
                len(entries) > 80
                or len({item.filename for item in entries}) != len(entries)
                or sum(item.file_size for item in entries) > MAX_UNCOMPRESSED
                or any(
                    item.file_size > MAX_UNCOMPRESSED
                    or item.file_size > max(item.compress_size, 1) * 200
                    or item.flag_bits & 1
                    or item.filename.startswith("/")
                    or ".." in item.filename.split("/")
                    or any(
                        word in item.filename.lower()
                        for word in (
                            "vbaproject",
                            "externallinks",
                            "activex",
                            "embeddings",
                            ".bin",
                        )
                    )
                    for item in entries
                )
            ):
                raise InvalidWorkbook("Недопустимый или слишком большой архив XLSX.")

            def xml(path):
                with book.open(path) as stream:
                    content = stream.read(MAX_UNCOMPRESSED + 1)
                if len(content) > MAX_UNCOMPRESSED:
                    raise InvalidWorkbook("Слишком большой XML в файле.")
                return ET.fromstring(content, forbid_dtd=True)

            for item in entries:
                if item.filename.endswith(".rels"):
                    for rel in xml(item.filename):
                        if rel.get("TargetMode") == "External":
                            raise InvalidWorkbook("Внешние ссылки в файле не поддерживаются.")
            workbook = xml("xl/workbook.xml")
            props = workbook.find(NS + "workbookPr")
            epoch = (
                date(1904, 1, 1)
                if props is not None and props.get("date1904") in {"1", "true"}
                else date(1899, 12, 30)
            )
            sheets = workbook.find(NS + "sheets")
            selected = [
                s for s in (sheets if sheets is not None else []) if s.get("name") == sheet_name
            ]
            if len(selected) != 1:
                raise InvalidWorkbook(f"Нужен один лист «{sheet_name}» из шаблона PERK.")
            relationships = xml("xl/_rels/workbook.xml.rels")
            targets = [
                r.get("Target", "")
                for r in relationships
                if r.get("Id") == selected[0].get(REL_NS + "id")
            ]
            if len(targets) != 1:
                raise InvalidWorkbook("Не найден лист с себестоимостью.")
            path = posixpath.normpath(
                targets[0].lstrip("/") if targets[0].startswith("/") else "xl/" + targets[0]
            )
            if not path.startswith("xl/worksheets/") or not path.endswith(".xml"):
                raise InvalidWorkbook("Неправильный путь к листу XLSX.")
            strings = []
            if "xl/sharedStrings.xml" in book.namelist():
                values = xml("xl/sharedStrings.xml")
                if len(values) > 30000:
                    raise InvalidWorkbook("Слишком много строковых значений.")
                strings = ["".join(v.itertext()) for v in values]

            grid = {}
            cells = xml(path).findall(".//" + NS + "c")
            if len(cells) > (MAX_ROWS + 1) * 5:
                raise InvalidWorkbook("В шаблоне допускается не более 5000 строк.")
            for cell in cells:
                if cell.find(NS + "f") is not None:
                    raise InvalidWorkbook("Замените формулы готовыми значениями.")
                match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", cell.get("r", ""))
                if not match:
                    raise InvalidWorkbook("Неправильная координата ячейки.")
                column, number = match[1], int(match[2])
                node = cell.find(NS + "v")
                value = "" if node is None else node.text or ""
                kind = cell.get("t", "n")
                if kind == "s":
                    if not re.fullmatch(r"[0-9]{1,7}", value) or int(value) >= len(strings):
                        raise InvalidWorkbook("Неправильная ссылка на строку в XLSX.")
                    value = strings[int(value)]
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//" + NS + "t"))
                elif kind not in {"n", "str", "d"}:
                    raise InvalidWorkbook("В таблице есть неподдерживаемое значение.")
                if len(value) > 2048 or number > MAX_ROWS + 1:
                    raise InvalidWorkbook("Превышен размер таблицы или ячейки.")
                if not value.strip():
                    continue
                if column not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[: len(headers)] or len(column) != 1:
                    raise InvalidWorkbook("Используйте только пять столбцов шаблона.")
                values = grid.setdefault(number, [""] * len(headers))
                index = ord(column) - ord("A")
                if values[index]:
                    raise InvalidWorkbook("В файле повторяется координата ячейки.")
                if (
                    len(headers) > 3
                    and headers[3] == "Действует с"
                    and column == "D"
                    and number > 1
                    and kind == "n"
                ):
                    serial = Decimal(value)
                    if serial != int(serial) or not 1 <= serial <= 100000:
                        raise InvalidWorkbook("В столбце «Действует с» нужна дата без времени.")
                    value = (epoch + timedelta(days=int(serial))).isoformat()
                values[index] = value.strip()
            if tuple(grid.pop(1, [])) != headers:
                raise InvalidWorkbook("Заголовки не совпадают с шаблоном PERK.")
            return sorted(grid.items())
    except InvalidWorkbook:
        raise
    except (
        BadZipFile,
        KeyError,
        IndexError,
        ValueError,
        InvalidOperation,
        OSError,
        DefusedXmlException,
        SyntaxError,
        OverflowError,
    ):
        raise InvalidWorkbook("Не удалось прочитать XLSX. Используйте шаблон PERK.") from None


def sheet_names(names, *, reserved=()):
    """Excel names are unique, case-insensitive, and no longer than 31 characters."""
    used = {name.casefold() for name in reserved}
    result = []
    for name in names:
        base = re.sub(r"[\[\]:*?/\\\x00-\x1f]", " ", name).strip(" '")[:31] or "Кабинет"
        candidate, suffix = base, 1
        while candidate.casefold() in used:
            suffix += 1
            ending = f" ({suffix})"
            candidate = base[: 31 - len(ending)] + ending
        used.add(candidate.casefold())
        result.append(candidate)
    return result


def column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def build_template(headers, rows=(), *, sheet_name="Себестоимость", numeric=False, extra_sheets=()):
    """Text-only workbook: identifiers keep leading zeroes; no executable formulas."""
    from html import escape
    from zipfile import ZIP_DEFLATED

    content = []
    for number, values in enumerate([headers, *rows], 1):
        cells = []
        for column, value in enumerate(values):
            address = f"{column_name(column + 1)}{number}"
            if (
                numeric
                and number > 1
                and isinstance(value, (int, Decimal))
                and not isinstance(value, bool)
            ):
                cell = f'<c r="{address}" t="n"><v>{value}</v></c>'
            else:
                text = escape(str(value) if value is not None else "")
                cell = f'<c r="{address}" t="inlineStr"><is><t>{text}</t></is></c>'
            cells.append(cell)
        cells = "".join(cells)
        content.append(f'<row r="{number}">{cells}</row>')
    files = {
        "[Content_Types].xml": """<Types
            xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
            <Default Extension="rels"
                ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
            <Default Extension="xml" ContentType="application/xml"/>
            <Override PartName="/xl/workbook.xml"
                ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
            <Override PartName="/xl/worksheets/sheet1.xml"
                ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
        </Types>""",
        "_rels/.rels": """<Relationships
            xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
            <Relationship Id="rId1"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
                Target="xl/workbook.xml"/>
        </Relationships>""",
        "xl/workbook.xml": """<workbook
            xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
            <sheets><sheet name="Себестоимость" sheetId="1" r:id="rId1"/></sheets>
        </workbook>""",
        "xl/_rels/workbook.xml.rels": """<Relationships
            xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
            <Relationship Id="rId1"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                Target="worksheets/sheet1.xml"/>
        </Relationships>""",
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(content) + "</sheetData></worksheet>",
    }
    files["xl/workbook.xml"] = files["xl/workbook.xml"].replace(
        'name="Себестоимость"', 'name="' + escape(sheet_name, quote=True) + '"'
    )
    for index, (name, columns, values) in enumerate(extra_sheets, 2):
        # Reuse the same text-only writer for auxiliary sheets.
        with ZipFile(
            BytesIO(build_template(columns, values, sheet_name=name, numeric=numeric))
        ) as source:
            files[f"xl/worksheets/sheet{index}.xml"] = source.read(
                "xl/worksheets/sheet1.xml"
            ).decode("utf-8")
        files["[Content_Types].xml"] = files["[Content_Types].xml"].replace(
            "</Types>",
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        )
        files["xl/workbook.xml"] = files["xl/workbook.xml"].replace(
            "</sheets>",
            f'<sheet name="{escape(name, quote=True)}" sheetId="{index}" '
            f'r:id="rId{index}"/></sheets>',
        )
        files["xl/_rels/workbook.xml.rels"] = files["xl/_rels/workbook.xml.rels"].replace(
            "</Relationships>",
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/></Relationships>',
        )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as book:
        for name, value in files.items():
            book.writestr(name, value.encode("utf-8"))
    return buffer.getvalue()
