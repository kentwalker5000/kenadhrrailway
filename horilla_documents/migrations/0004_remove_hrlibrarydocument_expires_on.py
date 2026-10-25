from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("horilla_documents", "0003_hrdocumentfolder_hrlibrarydocument"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="hrlibrarydocument",
            name="expires_on",
        ),
    ]
