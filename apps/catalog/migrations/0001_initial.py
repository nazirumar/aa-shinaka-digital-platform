# Generated for Phase 4 catalog initial schema

import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("locations", "0001_initial"),
    ]

    operations = [
        # Minimal placeholder — will be replaced by makemigrations logic? 
        # Actually easier to let makemigrations create it correctly after full models; 
        # but I need to write full model set first. Let me write a proper migration next.
        migrations.RunPython(lambda apps, s: None),  # no-op
    ]
