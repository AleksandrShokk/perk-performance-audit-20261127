"""Patch two worksheet columns while preserving namespaces and untouched ZIP parts."""

import hashlib
import posixpath
import re
from bisect import bisect_right
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.dom import Node
from xml.parsers.expat import ExpatError
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from defusedxml import minidom
from defusedxml.common import DefusedXmlException

from app.modules.supplies.template_schemas import TemplateColumn, TemplateHeader, TemplateSheet

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_UPLOAD = 256 * 1024
MAX_XML = 12 * 1024 * 1024
MAX_CELLS = 100000


class InvalidTemplate(ValueError):
    pass


def children(node, name):
    return [
        child
        for child in node.childNodes
        if child.nodeType == Node.ELEMENT_NODE
        and child.namespaceURI == NS
        and child.localName == name
    ]


def text(node):
    return "".join(
        child.data if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE) else text(child)
        for child in node.childNodes
    )


def column_number(value):
    result = 0
    for letter in value:
        result = result * 26 + ord(letter) - 64
    if not re.fullmatch(r"[A-Z]{1,3}", value) or not 1 <= result <= 16384:
        raise InvalidTemplate("Неправильный столбец XLSX.")
    return result


def coordinate(value):
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", value)
    if not match or int(match[2]) > 1048576:
        raise InvalidTemplate("Неправильная координата ячейки.")
    column_number(match[1])
    return match[1], int(match[2])


class Workbook:
    def __init__(self, payload):
        self.docs, self.parts = {}, {}
        if len(payload) > MAX_UPLOAD:
            raise InvalidTemplate("Размер шаблона — до 256 КБ.")
        self.digest = hashlib.sha256(payload).hexdigest()
        try:
            with ZipFile(BytesIO(payload)) as book:
                entries = book.infolist()
                self.infos = {entry.filename: entry for entry in entries}
                self.comment = book.comment
                if (
                    len(entries) > 128
                    or len({e.filename for e in entries}) != len(entries)
                    or sum(e.file_size for e in entries) > MAX_XML
                ):
                    raise InvalidTemplate("Слишком большой или повреждённый XLSX.")
                for entry in entries:
                    name = entry.filename
                    if (
                        entry.flag_bits & 1
                        or name.startswith("/")
                        or "\\" in name
                        or ".." in name.split("/")
                        or ":" in name
                        or posixpath.normpath(name.rstrip("/")) != name.rstrip("/")
                        or entry.file_size > max(entry.compress_size, 1) * 200
                        or any(
                            word in name.lower()
                            for word in (
                                "vbaproject",
                                "externallinks",
                                "activex",
                                "embeddings",
                                ".bin",
                                "connections",
                                "querytables",
                                "macrosheets",
                                "customui",
                            )
                        )
                    ):
                        raise InvalidTemplate(
                            "Этот XLSX содержит неподдерживаемые вложения или ссылки."
                        )
                    self.parts[name] = book.read(entry)
            for name, raw in self.parts.items():
                if name.endswith((".xml", ".rels")):
                    with self.parse(raw) as doc:
                        if len(
                            doc.getElementsByTagName("*")
                        ) > 150000 or doc.getElementsByTagNameNS(NS, "f"):
                            raise InvalidTemplate("Используйте шаблон без формул в ячейках.")
                        if any(
                            node.getAttribute("TargetMode") == "External"
                            for node in doc.getElementsByTagName("*")
                        ):
                            raise InvalidTemplate("Внешние ссылки в шаблоне не поддерживаются.")
            content_types = self.xml("[Content_Types].xml")
            main_types = [
                node.getAttribute("ContentType")
                for node in content_types.getElementsByTagNameNS(
                    "http://schemas.openxmlformats.org/package/2006/content-types", "Override"
                )
                if node.getAttribute("PartName") == "/xl/workbook.xml"
            ]
            if main_types != [
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
            ]:
                raise InvalidTemplate("Поддерживается обычный XLSX без макросов.")
            workbook = self.xml("xl/workbook.xml")
            if workbook.documentElement.namespaceURI != NS:
                raise InvalidTemplate("Нужен обычный файл XLSX.")
            relations = {
                node.getAttribute("Id"): node.getAttribute("Target")
                for node in self.xml("xl/_rels/workbook.xml.rels").getElementsByTagName(
                    "Relationship"
                )
            }
            self.sheets = {}
            for sheet in workbook.getElementsByTagNameNS(NS, "sheet"):
                target = relations[sheet.getAttributeNS(REL, "id")]
                path = posixpath.normpath(
                    target.lstrip("/") if target.startswith("/") else "xl/" + target
                )
                if (
                    not path.startswith("xl/worksheets/")
                    or not path.endswith(".xml")
                    or path not in self.parts
                    or sheet.getAttribute("name") in self.sheets
                ):
                    raise InvalidTemplate("Неправильная структура листов XLSX.")
                self.sheets[sheet.getAttribute("name")] = path
            if not self.sheets or len(self.sheets) > 20:
                raise InvalidTemplate("В XLSX должно быть от 1 до 20 листов.")
            self.strings = (
                [
                    text(node)
                    for node in self.xml("xl/sharedStrings.xml").getElementsByTagNameNS(NS, "si")
                ]
                if "xl/sharedStrings.xml" in self.parts
                else []
            )
            if len(self.strings) > 50000:
                raise InvalidTemplate("Слишком много строк в XLSX.")
        except (BadZipFile, KeyError, ValueError, ExpatError, DefusedXmlException, OSError) as exc:
            self.close()
            if isinstance(exc, InvalidTemplate):
                raise
            raise InvalidTemplate(
                "Не удалось прочитать XLSX. Выберите исходный шаблон площадки."
            ) from None

    @staticmethod
    def parse(raw):
        return minidom.parseString(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)

    def xml(self, name):
        if name not in self.docs:
            self.docs[name] = self.parse(self.parts[name])
        return self.docs[name]

    def close(self):
        for doc in self.docs.values():
            doc.unlink()
        self.docs.clear()

    def value(self, cell):
        if cell is None:
            return ""
        kind = cell.getAttribute("t")
        values = children(cell, "v")
        value = text(values[0]) if values else ""
        if kind == "s":
            if not value.isdecimal() or int(value) >= len(self.strings):
                raise InvalidTemplate("Повреждённый список строк XLSX.")
            value = self.strings[int(value)]
        elif kind == "inlineStr":
            value = "".join(text(node) for node in children(cell, "is"))
        elif kind not in {"", "n", "str"}:
            raise InvalidTemplate("В таблице есть неподдерживаемый тип ячейки.")
        if len(value) > 4096:
            raise InvalidTemplate("Слишком длинное значение в ячейке.")
        return value.strip()

    def grid(self, name):
        if name not in self.sheets:
            raise InvalidTemplate("Лист не найден.")
        doc = self.xml(self.sheets[name])
        data = doc.getElementsByTagNameNS(NS, "sheetData")
        if len(data) != 1:
            raise InvalidTemplate("На листе не найдена таблица.")
        rows, grid, count = {}, {}, 0
        for row in children(data[0], "row"):
            number = int(row.getAttribute("r"))
            if number in rows or not 1 <= number <= 1048576:
                raise InvalidTemplate("Неправильные номера строк XLSX.")
            rows[number], grid[number] = row, {}
            for cell in children(row, "c"):
                column, cell_row = coordinate(cell.getAttribute("r"))
                if cell_row != number or column in grid[number]:
                    raise InvalidTemplate("Повтор или несовпадение координат XLSX.")
                grid[number][column] = cell
                count += 1
        if count > MAX_CELLS:
            raise InvalidTemplate("Слишком много ячеек в шаблоне.")
        return doc, data[0], rows, grid

    def inspect(self):
        result = []
        for name in self.sheets:
            _, _, _, grid = self.grid(name)
            headers = []
            for number, cells in sorted(grid.items()):
                if number > 50:
                    break
                columns = [
                    TemplateColumn(key=key, label=self.value(cell)[:120])
                    for key, cell in cells.items()
                    if column_number(key) <= 60 and self.value(cell)
                ]
                if len(columns) >= 2:
                    headers.append(TemplateHeader(row=number, columns=columns))
            result.append(TemplateSheet(name=name, headers=headers))
        return result

    def fill(self, mapping, positions):
        key, quantity = mapping.identifier_column, mapping.quantity_column
        if key == quantity or mapping.first_row <= mapping.header_row:
            raise InvalidTemplate("Проверьте столбцы и первую строку товаров.")
        column_number(key), column_number(quantity)
        doc, data, rows, grid = self.grid(mapping.sheet)
        if not self.value(grid.get(mapping.header_row, {}).get(key)) or not self.value(
            grid.get(mapping.header_row, {}).get(quantity)
        ):
            raise InvalidTemplate("Выбранные столбцы не имеют заголовков.")
        for merge in doc.getElementsByTagNameNS(NS, "mergeCell"):
            start, end = merge.getAttribute("ref").split(":")
            a, first = coordinate(start)
            b, last = coordinate(end)
            if last >= mapping.first_row and any(
                column_number(a) <= column_number(c) <= column_number(b) for c in (key, quantity)
            ):
                raise InvalidTemplate("В области товаров есть объединённые ячейки.")
        targets = []
        if mapping.mode == "match":
            index = {}
            for number, cells in grid.items():
                if number < mapping.first_row:
                    continue
                value = self.value(cells.get(key))
                if not value:
                    continue
                index.setdefault(value, []).append(number)
                previous = self.value(cells.get(quantity))
                if previous:
                    try:
                        numeric = Decimal(previous)
                        if (
                            not numeric.is_finite()
                            or not 0 <= numeric <= 2147483647
                            or numeric != int(numeric)
                        ):
                            raise InvalidOperation
                    except InvalidOperation:
                        raise InvalidTemplate(
                            f"В строке {number} вместо количества указано другое значение."
                        ) from None
            missing = [p.identifier for p in positions if p.identifier not in index]
            if missing and index and not any(p.identifier in index for p in positions):
                first = next(iter(index))
                raise InvalidTemplate(
                    f"Ни одна из {sum(map(len, index.values()))} строк файла не совпала "
                    f"с товарами плана. Первая: {first}. "
                    "Для добавления товаров используйте «Загрузить товары из XLSX» в плане."
                )
            if missing:
                raise InvalidTemplate(
                    f"В файле нет {len(missing)} позиций из плана (например, {missing[0]}). "
                    "Это заполнение шаблона, а не загрузка товаров в план. "
                    "Для добавления используйте «Загрузить товары из XLSX» в плане."
                )
            wanted = {p.identifier: p.quantity for p in positions}
            for value, numbers in index.items():
                if value in wanted and len(numbers) != 1:
                    raise InvalidTemplate(
                        "Идентификатор повторяется на листе. Нельзя выбрать строку однозначно."
                    )
                targets.extend((number, None, wanted.get(value, 0)) for number in numbers)
        else:
            if any(
                self.value(cell)
                for number, cells in grid.items()
                if number >= mapping.first_row
                for cell in cells.values()
            ):
                raise InvalidTemplate(
                    "В шаблоне уже есть данные. Выберите «Товары уже в файле» "
                    "или загрузите пустой шаблон."
                )
            if doc.getElementsByTagNameNS(NS, "tablePart"):
                raise InvalidTemplate(
                    "Для форматированной таблицы используйте заполнение существующих строк."
                )
            targets = [
                (mapping.first_row + index, p.identifier, p.quantity)
                for index, p in enumerate(positions)
            ]
        if len(targets) > 20000:
            raise InvalidTemplate("В области товаров больше 20000 строк.")
        prototype = rows.get(mapping.first_row)
        original_numbers = sorted(rows)
        for number, identifier, value in targets:
            if number not in rows:
                row = (
                    prototype.cloneNode(deep=True)
                    if prototype is not None
                    else doc.createElementNS(NS, (data.prefix + ":" if data.prefix else "") + "row")
                )
                row.setAttribute("r", str(number))
                for cell in children(row, "c"):
                    column, _ = coordinate(cell.getAttribute("r"))
                    cell.setAttribute("r", f"{column}{number}")
                position = bisect_right(original_numbers, number)
                following = (
                    rows[original_numbers[position]] if position < len(original_numbers) else None
                )
                data.insertBefore(row, following)
                rows[number], grid[number] = (
                    row,
                    {coordinate(c.getAttribute("r"))[0]: c for c in children(row, "c")},
                )
            for column, content in ((key, identifier), (quantity, value)):
                if content is None:
                    continue
                cell = grid[number].get(column)
                if cell is None:
                    cell = doc.createElementNS(NS, (data.prefix + ":" if data.prefix else "") + "c")
                    cell.setAttribute("r", f"{column}{number}")
                    following = next(
                        (
                            c
                            for col, c in sorted(
                                grid[number].items(), key=lambda pair: column_number(pair[0])
                            )
                            if column_number(col) > column_number(column)
                        ),
                        None,
                    )
                    rows[number].insertBefore(cell, following)
                    grid[number][column] = cell
                for child in list(cell.childNodes):
                    cell.removeChild(child).unlink()
                prefix = cell.prefix + ":" if cell.prefix else ""
                cell.setAttribute("t", "inlineStr" if isinstance(content, str) else "n")
                node = doc.createElementNS(NS, prefix + ("is" if isinstance(content, str) else "v"))
                if isinstance(content, str):
                    node.appendChild(doc.createElementNS(NS, prefix + "t"))
                    node.firstChild.setAttributeNS(
                        "http://www.w3.org/XML/1998/namespace", "xml:space", "preserve"
                    )
                    node.firstChild.appendChild(doc.createTextNode(content))
                else:
                    node.appendChild(doc.createTextNode(str(content)))
                cell.appendChild(node)
        filters = doc.getElementsByTagNameNS(NS, "autoFilter")
        if mapping.mode == "append" and targets:
            for autofilter in filters:
                area = autofilter.getAttribute("ref").split(":")
                first_column, header = coordinate(area[0])
                last_column, last_row = coordinate(area[-1])
                if (
                    header == mapping.header_row
                    and column_number(first_column)
                    <= min(column_number(key), column_number(quantity))
                    and column_number(last_column)
                    >= max(column_number(key), column_number(quantity))
                ):
                    autofilter.setAttribute(
                        "ref", f"{area[0]}:{last_column}{max(last_row, max(t[0] for t in targets))}"
                    )
        dimensions = doc.getElementsByTagNameNS(NS, "dimension")
        if dimensions and targets:
            old = dimensions[0].getAttribute("ref").split(":")[-1]
            last_column, last_row = coordinate(old)
            end_column = max([last_column, key, quantity], key=column_number)
            dimensions[0].setAttribute(
                "ref", f"A1:{end_column}{max(last_row, max(t[0] for t in targets))}"
            )
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as book:
            book.comment = self.comment
            for name, raw in self.parts.items():
                book.writestr(
                    self.infos[name],
                    doc.toxml(encoding="utf-8") if name == self.sheets[mapping.sheet] else raw,
                )
        return output.getvalue()
