from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


def _column_name(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def write_xlsx(
    path: Path,
    headers: Sequence[str],
    rows: Sequence[Mapping[str, object]],
    sheet_name: str = "export",
) -> Path:
    """Crea un XLSX mínimo con cadenas compartidas para los tests."""
    shared: list[str] = []
    positions: dict[str, int] = {}

    def shared_index(value: str) -> int:
        if value not in positions:
            positions[value] = len(shared)
            shared.append(value)
        return positions[value]

    def row_xml(row_number: int, values: Sequence[object]) -> str:
        cells = []
        for column, value in enumerate(values):
            if value is None or value == "":
                continue
            reference = f"{_column_name(column)}{row_number}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                index = shared_index(str(value))
                cells.append(f'<c r="{reference}" t="s"><v>{index}</v></c>')
        return f'<row r="{row_number}">' + "".join(cells) + "</row>"

    sheet_rows = [row_xml(1, list(headers))]
    for number, row in enumerate(rows, start=2):
        sheet_rows.append(row_xml(number, [row.get(header, "") for header in headers]))

    shared_xml = "".join(f"<si><t>{escape(value)}</t></si>" for value in shared)
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    safe_sheet_name = escape(sheet_name, {'"': "&quot;"})
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{safe_sheet_name}" '
        'sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{len(shared)}" uniqueCount="{len(shared)}">{shared_xml}</sst>',
        )
    return path


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def xlsx_factory() -> Callable[..., Path]:
    return write_xlsx
