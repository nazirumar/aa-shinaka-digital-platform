"""Map Phase 1 role values onto the Phase 2 role set and create role groups."""

from django.db import migrations

# Phase 1 role value -> Phase 2 role value.
ROLE_MAP = {
    "farmer": "customer",
    "consultancy_client": "customer",
    "trainee": "customer",
    "export_buyer": "customer",
    "field_agent": "sales_officer",
    "marketing_officer": "sales_officer",
    "warehouse_staff": "inventory_officer",
    "trainer": "training_manager",
    "manager": "administrator",
    "admin": "administrator",
    # Unchanged: customer, consultant, export_officer, finance_officer.
}


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for old, new in ROLE_MAP.items():
        User.objects.filter(role=old).update(role=new)
    # Ensure every superuser carries the owner role.
    User.objects.filter(is_superuser=True).exclude(role="owner").update(role="owner")

    # Create/refresh role groups now that all custom permissions exist.
    from apps.accounts.roles import sync_role_groups, sync_user_groups

    sync_role_groups()
    for user in User.objects.all():
        sync_user_groups(user)


def backwards(apps, schema_editor):
    # Role remapping is not reversible; the reverse map is ambiguous.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_user_options_user_email_verification_nonce_and_more"),
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
