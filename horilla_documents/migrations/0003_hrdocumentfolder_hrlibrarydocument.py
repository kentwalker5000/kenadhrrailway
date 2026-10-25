# Generated manually for the HR-owned document library.

import django.db.models.deletion
import horilla.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("base", "0016_seed_default_export_permission"),
        ("horilla_documents", "0002_alter_document_reject_reason"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HRDocumentFolder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("name", models.CharField(max_length=120, verbose_name="Folder name")),
                ("description", models.TextField(blank=True, verbose_name="Description")),
                ("company_id", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="base.company", verbose_name="Company")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="Created By")),
                ("modified_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified_by", to=settings.AUTH_USER_MODEL, verbose_name="Modified By")),
            ],
            options={"verbose_name": "HR document folder", "verbose_name_plural": "HR document folders", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="HRLibraryDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("title", models.CharField(max_length=150, verbose_name="Title")),
                ("description", models.TextField(blank=True, verbose_name="Description")),
                ("document", models.FileField(upload_to=horilla.models.upload_path, verbose_name="Document")),
                ("expires_on", models.DateField(blank=True, null=True, verbose_name="Expires on")),
                ("company_id", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="base.company", verbose_name="Company")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="Created By")),
                ("modified_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified_by", to=settings.AUTH_USER_MODEL, verbose_name="Modified By")),
                ("folder", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documents", to="horilla_documents.hrdocumentfolder", verbose_name="Folder")),
            ],
            options={"verbose_name": "HR library document", "verbose_name_plural": "HR library documents", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="hrdocumentfolder",
            constraint=models.UniqueConstraint(fields=("company_id", "name"), name="unique_hr_document_folder_name"),
        ),
    ]
