"""Report export encoders — CSV, XLSX and PDF (Phase 11 — Task 13).

No third-party spreadsheet/PDF library is used (``AGENTS.md`` forbids new
dependencies): CSV comes from :mod:`csv`, XLSX is a hand-built Open XML package
(:mod:`zipfile`), and PDF uses :mod:`apps.analytics.pdf`.

Two safety rules are applied to every text cell:

* **Formula-injection guard** — text beginning with ``=``, ``+``, ``-``, ``@``,
  TAB or CR is prefixed with an apostrophe so a spreadsheet treats it as text.
* **Type fidelity** — numeric cells stay numeric in XLSX; everything else is an
  inline string, so no locale/format ambiguity is introduced.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .pdf import render_table_pdf

#: Characters that make a spreadsheet treat a cell as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

CONTENT_TYPES_BY_FORMAT = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}

NUMERIC_KINDS = ("number", "money", "percent")


def guard(value):
    """Neutralise spreadsheet formula injection in a text value."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def format_cell(column, value) -> str:
    """Render one cell value as a display string for ``column``."""
    if value is None or value == "":
        return ""
    if column.kind == "datetime":
        if isinstance(value, datetime):
            return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
        return str(value)
    if column.kind == "date":
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)
    if column.kind in ("money", "percent"):
        return str(Decimal(value).quantize(Decimal("0.01")))
    return str(value)


def _is_numeric(column, value) -> bool:
    if column.kind not in ("number", "money", "percent"):
        return False
    if value is None or value == "":
        return False
    try:
        Decimal(value)
    except (TypeError, ValueError, InvalidOperation):
        return False
    return True


def safe_filename(base: str, extension: str) -> str:
    """A filesystem/HTTP-safe filename derived from a report label."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base or "").strip("-._")
    return f"{(slug or 'report')[:80]}.{extension.lstrip('.')}"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def write_csv(columns, rows) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([column.label for column in columns])
    for row in rows:
        writer.writerow([guard(format_cell(column, row.get(column.key))) for column in columns])
    # UTF-8 BOM keeps Excel happy while remaining valid UTF-8 everywhere else.
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# XLSX (minimal, dependency-free Open XML)
# ---------------------------------------------------------------------------


def _xml(text) -> str:
    text = "" if text is None else str(text)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "-", name or "Report").strip() or "Report"
    return cleaned[:31]


def _sheet_xml(columns, rows, *, title: str) -> str:
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    row_index = 1
    if title:
        parts.append(
            f'<row r="{row_index}"><c r="A{row_index}" t="inlineStr">'
            f"<is><t>{_xml(title)}</t></is></c></row>"
        )
        row_index += 1

    parts.append(f'<row r="{row_index}">')
    for col_index, column in enumerate(columns):
        ref = f"{_column_letter(col_index)}{row_index}"
        parts.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml(column.label)}</t></is></c>')
    parts.append("</row>")
    row_index += 1

    for row in rows:
        parts.append(f'<row r="{row_index}">')
        for col_index, column in enumerate(columns):
            value = row.get(column.key)
            ref = f"{_column_letter(col_index)}{row_index}"
            if _is_numeric(column, value):
                parts.append(f'<c r="{ref}"><v>{_xml(format_cell(column, value))}</v></c>')
            else:
                text = guard(format_cell(column, value))
                if text == "":
                    continue
                parts.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml(text)}</t></is></c>')
        parts.append("</row>")
        row_index += 1

    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_name: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xml(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def _workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )


def write_xlsx(columns, rows, *, sheet_name: str = "Report", title: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml(_sheet_name(sheet_name)))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(columns, rows, title=title))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def write_pdf(columns, rows, *, title: str, subtitle: str = "", footer: str = "") -> bytes:
    headers = [column.label for column in columns]
    data = [[format_cell(column, row.get(column.key)) for column in columns] for row in rows]
    return render_table_pdf(
        title=title, subtitle=subtitle, headers=headers, rows=data, footer=footer
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def generate(
    columns, rows, *, export_format: str, title: str, subtitle: str = "", footer: str = ""
) -> bytes:
    if export_format == "csv":
        return write_csv(columns, rows)
    if export_format == "xlsx":
        return write_xlsx(columns, rows, sheet_name=title, title=title)
    if export_format == "pdf":
        return write_pdf(columns, rows, title=title, subtitle=subtitle, footer=footer)
    raise ValueError(f"Unsupported export format: {export_format!r}")


__all__ = [
    "CONTENT_TYPES_BY_FORMAT",
    "generate",
    "safe_filename",
    "write_csv",
    "write_pdf",
    "write_xlsx",
]
