"""Update product branding only where default tour copy is unchanged."""

from django.db import migrations


TOUR_COPY = [
    ("dashboard-overview", "description", "A quick look at your Horilla home dashboard."),
    ("settings-company", "description", "How to add and configure your company profile in Horilla."),
]

STEP_COPY = [
    ("getting-started", "title", "Welcome to Horilla 👋"),
    (
        "dashboard-overview", "description",
        "This is your home base. KPIs, charts and quick actions "
        "update automatically as your team uses Horilla.",
    ),
    (
        "payroll-overview", "description",
        "Generate payslips for a pay period in one click — Horilla calculates "
        "gross pay, deductions and net pay automatically.",
    ),
    (
        "settings-overview", "description",
        "Start with your company profile — name, logo, address and contact details. "
        "Everything in Horilla is scoped to a company, so this must exist before anything else.",
    ),
    (
        "settings-company", "description",
        "This page lists all companies registered in Horilla. Every employee, leave "
        "policy, payroll run and setting is scoped to a company — so you need at "
        "least one before you can do anything else.",
    ),
    (
        "settings-company", "description",
        "Horilla supports multiple companies in a single instance. Each company "
        "has its own employees, leave balances, payroll and reports — fully isolated from each other.",
    ),
    (
        "settings-company", "description",
        "This is the Company page. Everything in Horilla — employees, leave, "
        "payroll — is scoped to a company, so you must create one first.",
    ),
    (
        "settings-work-type", "description",
        "Click Create and give the work type a name. Horilla comes with common "
        "defaults — add any custom types your company uses.",
    ),
    (
        "settings-employee-shift", "description",
        "If employees rotate through different shifts (morning one week, evening "
        "the next), use the Rotating Shift feature to define the rotation schedule "
        "— Horilla will automatically assign the correct shift each period.",
    ),
]


def update_copy(apps, schema_editor, reverse=False):
    Tour = apps.get_model("horilla_tour", "Tour")
    TourStep = apps.get_model("horilla_tour", "TourStep")
    alias = schema_editor.connection.alias
    for slug, field, original in TOUR_COPY:
        branded = original.replace("Horilla", "KenadHr")
        old, new = (branded, original) if reverse else (original, branded)
        Tour.objects.using(alias).filter(
            slug=slug, company_id__isnull=True, **{field: old}
        ).update(**{field: new})
    for slug, field, original in STEP_COPY:
        branded = original.replace("Horilla", "KenadHr")
        old, new = (branded, original) if reverse else (original, branded)
        TourStep.objects.using(alias).filter(
            tour__slug=slug, tour__company_id__isnull=True, **{field: old}
        ).update(**{field: new})


def forwards(apps, schema_editor):
    update_copy(apps, schema_editor)


def backwards(apps, schema_editor):
    update_copy(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [("horilla_tour", "0087_seed_faq_view_tour")]
    operations = [migrations.RunPython(forwards, backwards)]
