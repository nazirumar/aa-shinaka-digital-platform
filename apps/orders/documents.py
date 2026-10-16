"""Invoice and receipt documents (HTML view + dependency-free PDF).

The project ships no PDF library: this module emits a small, valid PDF 1.4 file
with the standard Helvetica fonts for the printable invoice/receipt. The HTML
templates render the same data for on-screen viewing. Both are read-only
representations of immutable invoice/receipt records.
"""

from __future__ import annotations

from decimal import Decimal

PAGE_WIDTH = 595  # A4 points
PAGE_HEIGHT = 842
MARGIN = 50

_STYLES = {
    "title": {"size": 20, "bold": True, "gap": 12},
    "heading": {"size": 12, "bold": True, "gap": 6},
    "normal": {"size": 10, "bold": False, "gap": 4},
    "small": {"size": 8, "bold": False, "gap": 3},
    "right": {"size": 10, "bold": False, "gap": 4, "align": "right"},
}


def _ascii(text) -> str:
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, size: float, max_width: float, bold: bool) -> list[str]:
    factor = 0.55 if bold else 0.5
    max_chars = max(12, int(max_width / (size * factor)))
    words = _ascii(text).split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) <= max_chars:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line or not lines:
        lines.append(line)
    return lines


def _render_pdf(blocks: list[tuple[str, str]]) -> bytes:
    pages: list[list[str]] = []
    ops: list[str] = []
    y = PAGE_HEIGHT - MARGIN
    max_width = PAGE_WIDTH - 2 * MARGIN

    def new_page() -> None:
        nonlocal ops, y
        ops = []
        pages.append(ops)
        y = PAGE_HEIGHT - MARGIN

    new_page()
    for text, style in blocks:
        spec = _STYLES.get(style, _STYLES["normal"])
        size = spec["size"]
        bold = spec["bold"]
        line_height = size + 4
        for line in _wrap(str(text), size, max_width, bold):
            if y < MARGIN + 30:
                new_page()
            font = "F2" if bold else "F1"
            if style == "right":
                width = len(line) * size * 0.5
                x = PAGE_WIDTH - MARGIN - width
            else:
                x = MARGIN
            ops.append(f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape(line)}) Tj ET")
            y -= line_height
        y -= spec["gap"]

    # Assemble the objects.
    bodies: dict[int, bytes] = {}
    bodies[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    page_ids = [5 + i * 2 for i in range(len(pages))]
    content_ids = [6 + i * 2 for i in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    bodies[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")
    bodies[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    bodies[4] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    for pid, cid, page_ops in zip(page_ids, content_ids, pages, strict=False):
        bodies[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {cid} 0 R >>"
        ).encode("latin-1")
        stream = "\n".join(page_ops).encode("latin-1", "replace")
        bodies[cid] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for obj_id in range(1, len(bodies) + 1):
        offsets[obj_id] = len(out)
        out += f"{obj_id} 0 obj\n".encode("latin-1")
        out += bodies[obj_id]
        out += b"\nendobj\n"
    xref_offset = len(out)
    count = len(bodies) + 1
    out += f"xref\n0 {count}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for obj_id in range(1, len(bodies) + 1):
        out += f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF").encode(
        "latin-1"
    )
    return bytes(out)


def _company_lines() -> list[str]:
    try:
        from apps.cms.models import SiteSetting

        setting = SiteSetting.load()
    except Exception:  # pragma: no cover - CMS not migrated yet
        return ["AA Shinaka"]
    lines = [setting.site_name or "AA Shinaka"]
    address = getattr(setting, "address_display", "") or ""
    if address:
        lines.append(address)
    if setting.phone:
        lines.append(f"Tel: {setting.phone}")
    if setting.email:
        lines.append(setting.email)
    return lines


def _money(currency: str, amount) -> str:
    if amount is None:
        amount = Decimal("0.00")
    return f"{currency} {Decimal(str(amount)):,.2f}"


def invoice_blocks(invoice, items) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = [("TAX INVOICE", "title")]
    for index, line in enumerate(_company_lines()):
        blocks.append((line, "heading" if index == 0 else "small"))
    blocks.append(("", "small"))
    blocks.append((f"Invoice number: {invoice.number}", "normal"))
    if invoice.issued_at:
        blocks.append((f"Issue date: {invoice.issued_at:%d %b %Y}", "normal"))
    blocks.append((f"Status: {invoice.get_status_display()}", "normal"))
    blocks.append((f"Currency: {invoice.currency}", "normal"))
    blocks.append(("", "normal"))
    blocks.append(("Billed to", "heading"))
    blocks.append((invoice.customer_name or "—", "normal"))
    if invoice.customer_email:
        blocks.append((invoice.customer_email, "small"))
    if invoice.customer_phone:
        blocks.append((invoice.customer_phone, "small"))
    if invoice.billing_address:
        for address_line in invoice.billing_address.splitlines():
            blocks.append((address_line, "small"))
    blocks.append(("", "normal"))
    blocks.append((f"Order: {invoice.order.number}", "normal"))
    blocks.append(("", "normal"))
    blocks.append(("Items", "heading"))
    for item in items:
        label = item.product_name
        if item.variant_name:
            label = f"{label} ({item.variant_name})"
        blocks.append(
            (
                f"{label}  ×  {item.quantity}  @  {_money(invoice.currency, item.unit_price)}"
                f"   =   {_money(invoice.currency, item.line_total)}",
                "normal",
            )
        )
    blocks.append(("", "normal"))
    blocks.append((f"Subtotal: {_money(invoice.currency, invoice.subtotal)}", "right"))
    if invoice.discount_amount:
        blocks.append((f"Discount: -{_money(invoice.currency, invoice.discount_amount)}", "right"))
    blocks.append((f"Shipping: {_money(invoice.currency, invoice.shipping_amount)}", "right"))
    blocks.append((f"Tax: {_money(invoice.currency, invoice.tax_amount)}", "right"))
    blocks.append((f"Total: {_money(invoice.currency, invoice.total)}", "heading"))
    if invoice.notes:
        blocks.append(("", "normal"))
        blocks.append((invoice.notes, "small"))
    blocks.append(("", "normal"))
    blocks.append(("Thank you for your business.", "small"))
    return blocks


def receipt_blocks(receipt) -> list[tuple[str, str]]:
    payment = receipt.payment
    blocks: list[tuple[str, str]] = [("PAYMENT RECEIPT", "title")]
    for index, line in enumerate(_company_lines()):
        blocks.append((line, "heading" if index == 0 else "small"))
    blocks.append(("", "small"))
    blocks.append((f"Receipt number: {receipt.number}", "normal"))
    if receipt.issued_at:
        blocks.append((f"Date: {receipt.issued_at:%d %b %Y}", "normal"))
    blocks.append(("", "normal"))
    customer_label = payment.customer.get_full_name() or payment.customer.email
    blocks.append((f"Received from: {customer_label}", "normal"))
    if payment.order_id:
        blocks.append((f"Order: {payment.order.number}", "normal"))
    elif payment.service_quotation_id:
        blocks.append((f"Service quotation: {payment.service_quotation.reference}", "normal"))
    elif getattr(payment, "training_enrollment_id", None):
        blocks.append((f"Training enrolment: {payment.training_enrollment.reference}", "normal"))
    blocks.append((f"Payment reference: {payment.reference}", "normal"))
    if payment.provider_reference:
        blocks.append((f"Provider reference: {payment.provider_reference}", "normal"))
    method = payment.get_method_display() or payment.channel or "—"
    blocks.append((f"Method: {method}", "normal"))
    blocks.append(("", "normal"))
    blocks.append((f"Amount received: {_money(receipt.currency, receipt.amount)}", "heading"))
    blocks.append(("", "normal"))
    blocks.append(("This receipt confirms a payment verified by AA Shinaka.", "small"))
    return blocks


def render_invoice_pdf(invoice, items) -> bytes:
    return _render_pdf(invoice_blocks(invoice, items))


def receipt_pdf(receipt) -> bytes:
    return _render_pdf(receipt_blocks(receipt))


# Backwards-friendly aliases
render_receipt_pdf = receipt_pdf


__all__ = [
    "invoice_blocks",
    "receipt_blocks",
    "receipt_pdf",
    "render_invoice_pdf",
    "render_receipt_pdf",
]
