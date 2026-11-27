from io import BytesIO
from zipfile import ZipFile

from app.modules.catalog import match_files
from app.modules.catalog.import_schemas import CatalogImportError
from app.modules.catalog.import_service import MATCH_HEADERS
from app.modules.finance.xlsx import read_rows


def test_correction_workbook_is_the_upload_template_and_retains_valid_rows():
    original = [(2, ["000-WB", "00001", "=OZON", "00002"]), (8, ["wrong", "", "", ""])]
    records = match_files.manual(original, [CatalogImportError(row=8, message="Артикул не найден")])
    payload, kind, filename = match_files.export(records)
    assert filename.endswith(".xlsx")
    assert read_rows(payload, headers=MATCH_HEADERS, sheet_name="Соответствия") == [
        (2, original[0][1]),
        (3, original[1][1]),
    ]
    assert read_rows(
        payload,
        headers=("Строка на листе Соответствия", "Что исправить"),
        sheet_name="Ошибки",
    ) == [(2, ["3", "Артикул не найден"])]
    with ZipFile(BytesIO(payload)) as book:
        assert b"<f>" not in book.read("xl/worksheets/sheet1.xml")


def test_large_repair_exports_split_into_individually_uploadable_templates(monkeypatch):
    monkeypatch.setattr(match_files, "MAX_ROWS", 2)
    rows = [([f"WB-{i}", f"00{i}", "", ""], "Нужна пара") for i in range(5)]
    payload, kind, filename = match_files.export(rows)
    assert kind == "application/zip" and filename.endswith(".zip")
    found = []
    with ZipFile(BytesIO(payload)) as archive:
        for name in sorted(archive.namelist()):
            content = archive.read(name)
            values = read_rows(content, headers=MATCH_HEADERS, sheet_name="Соответствия")
            assert len(values) <= 2
            found.extend(cells for _, cells in values)
    assert found == [cells for cells, _ in rows]
