"""Seed the configurable export document types (Task 6).

These are *types* of document AA Shinaka may collect (proforma invoice,
phytosanitary certificate, etc.) — never generated official certificates and
never a claim of government approval. Staff configure which are required per
destination.
"""

from __future__ import annotations

from django.db import migrations

DOCUMENT_TYPES = [
    {
        "code": "proforma_invoice",
        "name": "Proforma invoice",
        "description": "Preliminary invoice stating the intended sale terms.",
        "requires_expiry": False,
        "is_official": False,
        "sort_order": 10,
    },
    {
        "code": "commercial_invoice",
        "name": "Commercial invoice",
        "description": "Final invoice for the shipped goods.",
        "requires_expiry": False,
        "is_official": False,
        "sort_order": 20,
    },
    {
        "code": "packing_list",
        "name": "Packing list",
        "description": "Itemised list of packages and contents.",
        "requires_expiry": False,
        "is_official": False,
        "sort_order": 30,
    },
    {
        "code": "certificate_of_origin",
        "name": "Certificate of origin",
        "description": "Document attesting the origin of the goods.",
        "requires_expiry": True,
        "is_official": True,
        "sort_order": 40,
    },
    {
        "code": "phytosanitary_certificate",
        "name": "Phytosanitary certificate",
        "description": "Certificate confirming plant health requirements are met.",
        "requires_expiry": True,
        "is_official": True,
        "sort_order": 50,
    },
    {
        "code": "export_declaration",
        "name": "Export declaration",
        "description": "Customs export declaration.",
        "requires_expiry": False,
        "is_official": True,
        "sort_order": 60,
    },
    {
        "code": "transport_document",
        "name": "Transport document",
        "description": "Bill of lading, airway bill or road transport document.",
        "requires_expiry": False,
        "is_official": False,
        "sort_order": 70,
    },
    {
        "code": "insurance_certificate",
        "name": "Insurance certificate",
        "description": "Cargo insurance certificate, where applicable.",
        "requires_expiry": True,
        "is_official": False,
        "sort_order": 80,
    },
    {
        "code": "other_permit",
        "name": "Other applicable permit",
        "description": "Any other permit the destination requires.",
        "requires_expiry": True,
        "is_official": True,
        "sort_order": 90,
    },
]


def seed_document_types(apps, schema_editor):
    ExportDocumentType = apps.get_model("export", "ExportDocumentType")
    for entry in DOCUMENT_TYPES:
        ExportDocumentType.objects.update_or_create(code=entry["code"], defaults=entry)


def remove_document_types(apps, schema_editor):
    ExportDocumentType = apps.get_model("export", "ExportDocumentType")
    ExportDocumentType.objects.filter(code__in=[e["code"] for e in DOCUMENT_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("export", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_document_types, remove_document_types),
    ]
