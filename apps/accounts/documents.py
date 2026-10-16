"""Customer document centre (Phase 10, Task 13).

Aggregates the documents a customer owns across every domain into one place and
provides a single **authorised** download route for files that have no dedicated
view of their own (service reports and customer-visible attachments).

Documents that already have an ownership-checked download view (invoices,
receipts, export documents, certificates) are linked to those views directly so
authorisation logic is never duplicated. Service files are resolved here with an
explicit per-type ownership filter — a raw primary key is never trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from django.urls import reverse


@dataclass
class DocumentItem:
    title: str
    subtitle: str
    created: date | datetime | None
    url: str


@dataclass
class DocumentSection:
    key: str
    label: str
    items: list[DocumentItem] = field(default_factory=list)


def _has_file(queryset):
    return queryset.exclude(file="").exclude(file__isnull=True)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def document_sections(customer) -> list[DocumentSection]:
    """Return the customer's documents grouped by domain, newest first."""
    sections = [
        _invoices_section(customer),
        _receipts_section(customer),
        _export_section(customer),
        _certificates_section(customer),
        _services_section(customer),
    ]
    return [section for section in sections if section.items]


def document_count(customer) -> int:
    return sum(len(section.items) for section in document_sections(customer))


def _invoices_section(customer) -> DocumentSection:
    from apps.orders.payment_models import Invoice

    section = DocumentSection(key="invoices", label="Invoices")
    invoices = Invoice.objects.filter(order__user=customer).order_by("-created_at")
    for invoice in invoices:
        section.items.append(
            DocumentItem(
                title=f"Invoice {invoice.number}",
                subtitle=f"{invoice.currency} {invoice.total}",
                created=invoice.issued_at or invoice.created_at,
                url=reverse("orders:invoice_pdf", args=[invoice.number]),
            )
        )
    return section


def _receipts_section(customer) -> DocumentSection:
    from apps.orders.payment_models import Receipt

    section = DocumentSection(key="receipts", label="Receipts")
    receipts = (
        Receipt.objects.filter(payment__customer=customer)
        .select_related("payment")
        .order_by("-created_at")
    )
    for receipt in receipts:
        section.items.append(
            DocumentItem(
                title=f"Receipt {receipt.number}",
                subtitle=f"{receipt.currency} {receipt.amount}",
                created=receipt.issued_at or receipt.created_at,
                url=reverse("orders:receipt_pdf", args=[receipt.number]),
            )
        )
    return section


def _export_section(customer) -> DocumentSection:
    from apps.export.models import ExportDocument

    section = DocumentSection(key="export", label="Export documents")
    documents = _has_file(
        ExportDocument.objects.filter(order__customer=customer, is_customer_visible=True)
        .select_related("document_type", "order")
        .order_by("-created_at")
    )
    for document in documents:
        section.items.append(
            DocumentItem(
                title=document.document_type.name,
                subtitle=f"Export order {document.order.reference}",
                created=document.created_at,
                url=reverse("export:document_download", args=[document.pk]),
            )
        )
    return section


def _certificates_section(customer) -> DocumentSection:
    from apps.training.models import Certificate

    section = DocumentSection(key="certificates", label="Certificates")
    certificates = (
        Certificate.objects.filter(student=customer)
        .select_related("course")
        .order_by("-issue_date", "-created_at")
    )
    for certificate in certificates:
        section.items.append(
            DocumentItem(
                title=f"Certificate {certificate.certificate_number}",
                subtitle=str(certificate.course),
                created=certificate.issue_date,
                url=reverse("training_account:certificate_download", args=[certificate.pk]),
            )
        )
    return section


def _services_section(customer) -> DocumentSection:
    from apps.services.models import (
        ConsultationReport,
        FarmProgressReport,
        MarketingActivity,
        ServiceAttachment,
        StorageInspection,
    )

    section = DocumentSection(key="services", label="Service reports & files")

    consultation_reports = _has_file(
        ConsultationReport.objects.filter(
            appointment__request__customer=customer, is_customer_visible=True
        ).select_related("appointment__request")
    ).order_by("-issued_at")
    for report in consultation_reports:
        section.items.append(
            DocumentItem(
                title=f"Consultation report — {report.appointment.request.reference}",
                subtitle="Consultancy",
                created=report.issued_at,
                url=reverse("account:document_download", args=["consultation-report", report.pk]),
            )
        )

    farm_reports = _has_file(
        FarmProgressReport.objects.filter(
            project__request__request__customer=customer, is_customer_visible=True
        ).select_related("project__request__request")
    ).order_by("-reported_at")
    for report in farm_reports:
        section.items.append(
            DocumentItem(
                title=report.title,
                subtitle=f"Farm project {report.project.request.request.reference}",
                created=report.reported_at,
                url=reverse("account:document_download", args=["farm-report", report.pk]),
            )
        )

    marketing_activities = _has_file(
        MarketingActivity.objects.filter(
            campaign__enquiry__request__customer=customer
        ).select_related("campaign__enquiry__request")
    ).order_by("-occurred_on", "-created_at")
    for activity in marketing_activities:
        section.items.append(
            DocumentItem(
                title=activity.title,
                subtitle=f"Marketing {activity.campaign.enquiry.request.reference}",
                created=activity.created_at,
                url=reverse("account:document_download", args=["marketing-report", activity.pk]),
            )
        )

    storage_inspections = _has_file(
        StorageInspection.objects.filter(
            booking__request__request__customer=customer
        ).select_related("booking__request__request")
    ).order_by("-inspected_at")
    for inspection in storage_inspections:
        section.items.append(
            DocumentItem(
                title=f"Storage inspection — {inspection.booking.request.request.reference}",
                subtitle=inspection.get_condition_display(),
                created=inspection.inspected_at,
                url=reverse(
                    "account:document_download", args=["storage-inspection", inspection.pk]
                ),
            )
        )

    attachments = _has_file(
        ServiceAttachment.objects.filter(
            request__customer=customer, is_customer_visible=True
        ).select_related("request")
    ).order_by("-created_at")
    for attachment in attachments:
        section.items.append(
            DocumentItem(
                title=attachment.label or "Service attachment",
                subtitle=f"Service request {attachment.request.reference}",
                created=attachment.created_at,
                url=reverse(
                    "account:document_download", args=["service-attachment", attachment.pk]
                ),
            )
        )

    return section


# ---------------------------------------------------------------------------
# Authorised resolution of a single service file
# ---------------------------------------------------------------------------


def _consultation_report_file(customer, pk):
    from apps.services.models import ConsultationReport

    return _has_file(
        ConsultationReport.objects.filter(
            pk=pk, is_customer_visible=True, appointment__request__customer=customer
        )
    ).first()


def _farm_report_file(customer, pk):
    from apps.services.models import FarmProgressReport

    return _has_file(
        FarmProgressReport.objects.filter(
            pk=pk, is_customer_visible=True, project__request__request__customer=customer
        )
    ).first()


def _marketing_report_file(customer, pk):
    from apps.services.models import MarketingActivity

    return _has_file(
        MarketingActivity.objects.filter(pk=pk, campaign__enquiry__request__customer=customer)
    ).first()


def _storage_inspection_file(customer, pk):
    from apps.services.models import StorageInspection

    return _has_file(
        StorageInspection.objects.filter(pk=pk, booking__request__request__customer=customer)
    ).first()


def _service_attachment_file(customer, pk):
    from apps.services.models import ServiceAttachment

    return _has_file(
        ServiceAttachment.objects.filter(
            pk=pk, request__customer=customer, is_customer_visible=True
        )
    ).first()


_SERVICE_FILE_RESOLVERS = {
    "consultation-report": _consultation_report_file,
    "farm-report": _farm_report_file,
    "marketing-report": _marketing_report_file,
    "storage-inspection": _storage_inspection_file,
    "service-attachment": _service_attachment_file,
}


def service_file(customer, kind: str, pk):
    """Return one customer-owned service file object, or ``None``."""
    resolver = _SERVICE_FILE_RESOLVERS.get(kind)
    if resolver is None:
        return None
    return resolver(customer, pk)
