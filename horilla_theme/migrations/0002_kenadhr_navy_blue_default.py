"""Make KenadHR's navy-blue palette the default theme."""

from django.db import migrations


NAVY_THEME = {
    "description": "KenadHR's professional navy-blue brand theme",
    "primary_50": "#f8fafc",
    "primary_100": "#eff6ff",
    "primary_200": "#dbeafe",
    "primary_300": "#bfdbfe",
    "primary_400": "#93c5fd",
    "primary_500": "#3b82f6",
    "primary_600": "#1d4ed8",
    "primary_700": "#1e3a8a",
    "primary_800": "#172554",
    "primary_900": "#0f172a",
    "dark_400": "#172554",
    "dark_600": "#0f172a",
    "secondary_400": "#93c5fd",
    "secondary_500": "#3b82f6",
    "secondary_600": "#1d4ed8",
}


def make_navy_default(apps, schema_editor):
    theme_model = apps.get_model("horilla_theme", "HorillaColorTheme")

    theme_model.objects.filter(is_default=True).update(is_default=False)
    theme_model.objects.filter(name="Navy Steel Theme").update(
        is_default=True,
        **NAVY_THEME,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("horilla_theme", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(make_navy_default, migrations.RunPython.noop),
    ]
