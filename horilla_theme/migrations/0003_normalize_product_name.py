from django.db import migrations


def rebrand(apps, schema_editor):
    apps.get_model("horilla_theme", "HorillaColorTheme").objects.using(
        schema_editor.connection.alias
    ).filter(
        description="KenadHR's professional navy-blue brand theme"
    ).update(description="KenadHr's professional navy-blue brand theme")


class Migration(migrations.Migration):
    dependencies = [("horilla_theme", "0002_kenadhr_navy_blue_default")]
    operations = [migrations.RunPython(rebrand, migrations.RunPython.noop)]
