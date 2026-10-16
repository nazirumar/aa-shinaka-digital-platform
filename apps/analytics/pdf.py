"""A tiny dependency-free PDF table renderer (Phase 11 — Task 13).

The project deliberately has no ``reportlab``/``weasyprint`` dependency (see
``AGENTS.md``), so report PDFs are produced with the standard library only. This
module emits a minimal, valid PDF: a title/subtitle, a header row, body rows with
page breaks, and optional footer text. All text is escaped and truncated to its
column width; characters are assumed Helvetica metrics (a conservative estimate is
used for truncation, never for layout correctness).

Only ASCII-safe text is emitted. Non-ASCII characters are replaced so the byte
offsets in the content streams always match the declared lengths.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

PAGE_LANDSCAPE = (842.0, 595.0)  # A4 landscape, points
PAGE_PORTRAIT = (595.0, 842.0)
MARGIN = 36.0
TITLE_SIZE = 15.0
SUBTITLE_SIZE = 9.0
BODY_SIZE = 8.5
HEADER_SIZE = 8.5
ROW_HEIGHT = 15.0
CHAR_WIDTH_RATIO = 0.5


def _ascii(text) -> str:
    if text is None:
        return ""
    if isinstance(text, (date, datetime)):
        text = text.isoformat()
    if isinstance(text, Decimal):
        text = format(text.normalize(), "f")
    text = str(text)
    return text.encode("ascii", "replace").decode("ascii")


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _truncate(text: str, width: float, size: float) -> str:
    max_chars = max(int(width / (size * CHAR_WIDTH_RATIO)), 1)
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 1, 0)] + "~"


def _text_op(x: float, y: float, size: float, font: str, text: str) -> bytes:
    return f"BT /{font} {size:g} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape(text)}) Tj ET\n".encode(
        "ascii"
    )


def _line_op(x1, y1, x2, y2, width=0.5) -> bytes:
    return f"{width:g} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S\n".encode("ascii")


def render_table_pdf(
    *,
    title: str,
    subtitle: str = "",
    headers: list[str],
    rows: list[list[str]],
    footer: str = "",
    landscape: bool = True,
) -> bytes:
    """Render a table to PDF bytes. ``rows`` must already be display strings."""
    page_w, page_h = PAGE_LANDSCAPE if landscape else PAGE_PORTRAIT
    content_w = page_w - 2 * MARGIN
    column_count = max(len(headers), 1)
    column_w = content_w / column_count

    top = page_h - MARGIN
    usable_bottom = MARGIN + (18 if footer else 0)

    pages: list[list[bytes]] = []
    current: list[bytes] = []

    def new_page() -> None:
        nonlocal current
        current = []
        pages.append(current)

    # Header of every page.
    def draw_header() -> float:
        y = top - TITLE_SIZE
        current.append(
            _text_op(MARGIN, y, TITLE_SIZE, "F2", _truncate(_ascii(title), content_w, TITLE_SIZE))
        )
        if subtitle:
            y -= SUBTITLE_SIZE + 4
            current.append(
                _text_op(
                    MARGIN,
                    y,
                    SUBTITLE_SIZE,
                    "F1",
                    _truncate(_ascii(subtitle), content_w, SUBTITLE_SIZE),
                )
            )
        y -= 8
        current.append(_line_op(MARGIN, y, page_w - MARGIN, y, 1.0))
        y -= ROW_HEIGHT
        for index, header in enumerate(headers):
            x = MARGIN + index * column_w + 2
            current.append(
                _text_op(
                    x, y, HEADER_SIZE, "F2", _truncate(_ascii(header), column_w - 4, HEADER_SIZE)
                )
            )
        y -= 4
        current.append(_line_op(MARGIN, y, page_w - MARGIN, y, 0.5))
        return y - ROW_HEIGHT

    new_page()
    y = draw_header()

    for row in rows:
        if y < usable_bottom:
            new_page()
            y = draw_header()
        for index in range(column_count):
            value = row[index] if index < len(row) else ""
            x = MARGIN + index * column_w + 2
            current.append(
                _text_op(x, y, BODY_SIZE, "F1", _truncate(_ascii(value), column_w - 4, BODY_SIZE))
            )
        y -= ROW_HEIGHT

    if not rows:
        current.append(_text_op(MARGIN, y, BODY_SIZE, "F1", "No data for this period."))

    if footer:
        for page in pages:
            page.append(
                _text_op(MARGIN, MARGIN - 12, 7.0, "F1", _truncate(_ascii(footer), content_w, 7.0))
            )

    return _serialise(pages, page_w, page_h)


def _serialise(pages: list[list[bytes]], page_w: float, page_h: float) -> bytes:
    """Assemble the PDF object graph."""
    objects: list[bytes] = []

    def add(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)  # 1-based object number

    # Placeholders first so we can reference object numbers.
    catalog_num = 1
    pages_num = 2
    font1_num = 3
    font2_num = 4
    first_page_num = 5
    first_content_num = first_page_num + len(pages)

    kids = " ".join(f"{first_page_num + i} 0 R" for i in range(len(pages)))

    add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))  # 2
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")  # 3
    add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )  # 4

    for i in range(len(pages)):
        content_num = first_content_num + i
        add(
            (
                f"<< /Type /Page /Parent {pages_num} 0 R "
                f"/MediaBox [0 0 {page_w:g} {page_h:g}] "
                f"/Resources << /Font << /F1 {font1_num} 0 R /F2 {font2_num} 0 R >> >> "
                f"/Contents {content_num} 0 R >>"
            ).encode("ascii")
        )
    for stream in pages:
        body = b"".join(stream)
        add(
            b"<< /Length " + str(len(body)).encode("ascii") + b" >>\nstream\n" + body + b"endstream"
        )

    # Byte-accurate cross reference table.
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii")
        out += payload
        out += b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(out)


__all__ = ["render_table_pdf"]
