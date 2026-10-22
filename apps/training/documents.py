"""Certificate document rendering (HTML view + dependency-free PDF).

Reuses the PDF writer from :mod:`apps.orders.documents` (the project ships no
PDF library) so a certificate can be downloaded as a real PDF. The same data is
rendered as an HTML page for on-screen viewing.
"""

from __future__ import annotations

PAGE_WIDTH = 842
PAGE_HEIGHT = 595
FOREST = (0.12, 0.30, 0.21)
HARVEST = (0.72, 0.49, 0.20)
INK = (0.16, 0.19, 0.17)
MUTED = (0.36, 0.39, 0.37)
PALE = (0.96, 0.95, 0.91)


def certificate_blocks(certificate) -> list[tuple[str, str]]:
    template = certificate.template
    title = (template.title if template else "") or "Certificate of Completion"
    student = certificate.student.full_name or certificate.student.email
    blocks: list[tuple[str, str]] = [
        (title.upper(), "title"),
        ("AA Shinaka Training Academy", "heading"),
        ("", "small"),
        (f"This is to certify that {student}", "normal"),
        (f"has successfully completed {certificate.course.title}", "normal"),
    ]
    if certificate.session is not None:
        blocks.append((f"Delivered in session {certificate.session.reference}", "normal"))
    blocks.append((f"Date of issue: {certificate.issue_date:%d %B %Y}", "normal"))
    blocks.append(("", "small"))
    blocks.append((f"Certificate number: {certificate.certificate_number}", "small"))
    blocks.append((f"Verification code: {certificate.verification_code}", "small"))
    if template and template.footer_text:
        blocks.append((template.footer_text, "small"))
    if certificate.status == "revoked":
        blocks.append(("THIS CERTIFICATE HAS BEEN REVOKED", "heading"))
    return blocks


def certificate_pdf(certificate) -> bytes:
    template = certificate.template
    title = (template.title if template else "") or "Certificate of Completion"
    student = certificate.student.full_name or certificate.student.email
    course = certificate.course.title
    ops: list[str] = []

    def fill_rect(
        x: float, y: float, width: float, height: float, color: tuple[float, ...]
    ) -> None:
        red, green, blue = color
        ops.append(
            f"q {red:.3f} {green:.3f} {blue:.3f} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f Q"
        )

    def stroke_rect(
        x: float, y: float, width: float, height: float, color: tuple[float, ...], line_width: float
    ) -> None:
        red, green, blue = color
        ops.append(
            f"q {red:.3f} {green:.3f} {blue:.3f} RG {line_width:.2f} w "
            f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re S Q"
        )

    def line(
        x1: float, y1: float, x2: float, y2: float, color: tuple[float, ...], line_width: float
    ) -> None:
        red, green, blue = color
        ops.append(
            f"q {red:.3f} {green:.3f} {blue:.3f} RG {line_width:.2f} w "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S Q"
        )

    def centered_text(
        text: str, y: float, size: float, *, bold: bool = False, color: tuple[float, ...] = INK
    ) -> None:
        font = "F2" if bold else "F1"
        red, green, blue = color
        width = len(text) * size * (0.56 if bold else 0.52)
        x = (PAGE_WIDTH - width) / 2
        safe_text = str(text).encode("latin-1", "replace").decode("latin-1")
        safe_text = safe_text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(
            f"q {red:.3f} {green:.3f} {blue:.3f} rg "
            f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm "
            f"({safe_text}) Tj ET Q"
        )

    def wrap(text: str, max_chars: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for word in str(text).split():
            pieces = [word[index : index + max_chars] for index in range(0, len(word), max_chars)]
            for piece in pieces:
                candidate = f"{current} {piece}".strip()
                if len(candidate) > max_chars and current:
                    lines.append(current)
                    current = piece
                else:
                    current = candidate
        if current or not lines:
            lines.append(current)
        return lines

    def centered_lines(
        text: str,
        y: float,
        size: float,
        max_chars: int,
        line_height: float,
        *,
        bold: bool = False,
        color: tuple[float, ...] = INK,
    ) -> float:
        lines = wrap(text, max_chars)
        for index, text_line in enumerate(lines):
            centered_text(text_line, y - index * line_height, size, bold=bold, color=color)
        return y - len(lines) * line_height

    fill_rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (1, 1, 1))
    stroke_rect(24, 22, 794, 551, FOREST, 2.4)
    stroke_rect(33, 31, 776, 533, HARVEST, 0.8)
    fill_rect(34, 480, 774, 83, PALE)
    fill_rect(34, 480, 5, 83, FOREST)
    fill_rect(803, 480, 5, 83, FOREST)

    centered_text("AA SHINAKA", 532, 16, bold=True, color=FOREST)
    centered_text("TRAINING ACADEMY", 513, 9, bold=True, color=HARVEST)
    title_end = centered_lines(title.upper(), 452, 22, 58, 27, bold=True, color=FOREST)
    divider_y = title_end - 1
    line(276, divider_y, 566, divider_y, HARVEST, 1.2)
    centered_text("THIS CERTIFICATE IS AWARDED TO", divider_y - 24, 9, bold=True, color=MUTED)
    student_end = centered_lines(student, divider_y - 62, 27, 44, 34, bold=True, color=FOREST)
    centered_text("for successfully completing", student_end - 14, 11, color=MUTED)
    course_end = centered_lines(course, student_end - 45, 17, 70, 22, bold=True, color=INK)

    detail_y = course_end - 8
    if certificate.session is not None:
        centered_text(
            f"Training session: {certificate.session.reference}",
            detail_y,
            9,
            color=MUTED,
        )
        detail_y -= 20
    centered_text(
        f"Issued on {certificate.issue_date:%d %B %Y}",
        detail_y,
        10,
        bold=True,
        color=INK,
    )

    stroke_rect(63, 98, 345, 52, (0.82, 0.84, 0.81), 0.7)
    stroke_rect(434, 98, 345, 52, (0.82, 0.84, 0.81), 0.7)
    centered_text("CERTIFICATE NUMBER", 131, 7.5, bold=True, color=MUTED)
    centered_text(certificate.certificate_number, 112, 9, bold=True, color=FOREST)
    centered_text("VERIFICATION CODE", 131, 7.5, bold=True, color=MUTED)
    centered_text(certificate.verification_code, 112, 8, bold=True, color=FOREST)

    if certificate.status == "revoked":
        centered_text(
            "REVOKED - THIS CERTIFICATE IS NO LONGER VALID",
            82,
            8,
            bold=True,
            color=(0.65, 0.12, 0.12),
        )
    elif template and template.footer_text:
        centered_lines(template.footer_text, 80, 8, 100, 10, color=MUTED)
    centered_text("Verify this certificate using the code above.", 61, 7.5, color=MUTED)

    stream = "\n".join(ops).encode("latin-1", "replace")
    bodies = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        ),
        5: (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents 6 0 R >>"
        ).encode("latin-1"),
        6: (f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"),
    }
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for object_id, body in bodies.items():
        offsets[object_id] = len(output)
        output += f"{object_id} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref_offset = len(output)
    output += b"xref\n0 7\n0000000000 65535 f \n"
    for object_id in range(1, 7):
        output += f"{offsets[object_id]:010d} 00000 n \n".encode("latin-1")
    output += f"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode(
        "latin-1"
    )
    return bytes(output)
