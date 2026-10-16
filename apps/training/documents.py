"""Certificate document rendering (HTML view + dependency-free PDF).

Reuses the PDF writer from :mod:`apps.orders.documents` (the project ships no
PDF library) so a certificate can be downloaded as a real PDF. The same data is
rendered as an HTML page for on-screen viewing.
"""

from __future__ import annotations

from apps.orders.documents import _render_pdf


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
    return _render_pdf(certificate_blocks(certificate))
