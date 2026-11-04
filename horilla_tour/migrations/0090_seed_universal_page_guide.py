"""Provide a useful manual tour on every authenticated application page."""

from django.db import migrations


SLUG = "page-navigation-guide"

STEPS = [
    {
        "sequence": 1,
        "title": "Welcome to this page",
        "description": "Each workspace in KenadHr follows the same pattern: use the page tools to work with records, then return here whenever you need a quick orientation.",
        "element_selector": "",
        "side": "over",
        "align": "start",
    },
    {
        "sequence": 2,
        "title": "Navigate between workspaces",
        "description": "Use the sidebar to move between HR areas. Expand a module to see its related pages; the current module remains open while you work.",
        "element_selector": "#sidebar",
        "side": "right",
        "align": "start",
    },
    {
        "sequence": 3,
        "title": "Your working area",
        "description": "This is the page workspace. Look for the search, filter, Create, Actions, and export controls here; the controls available depend on your permissions and this page.",
        "element_selector": "#ohMainContent",
        "side": "left",
        "align": "start",
    },
    {
        "sequence": 4,
        "title": "Replay a guide anytime",
        "description": "Select the question-mark button in the top bar to reopen this guide or a more detailed page-specific tour whenever one is available.",
        "element_selector": "#tourLauncherBtn",
        "side": "bottom",
        "align": "end",
    },
]


def seed(apps, schema_editor):
    Tour = apps.get_model("horilla_tour", "Tour")
    TourStep = apps.get_model("horilla_tour", "TourStep")
    tour, created = Tour.objects.get_or_create(
        slug=SLUG,
        defaults={
            "title": "Using This Page",
            "description": "A short guide available from every KenadHr workspace.",
            # An empty page match intentionally applies to every page. This is
            # a manual fallback; detailed page tours still auto-start normally.
            "page_match": "",
            "match_type": "url_name",
            "audience": "all",
            "trigger": "manual",
            "priority": -100,
            "icon": "compass-outline",
            "is_published": True,
        },
    )
    if not created:
        return
    for step in STEPS:
        TourStep.objects.create(tour=tour, **step)


def unseed(apps, schema_editor):
    apps.get_model("horilla_tour", "Tour").objects.filter(slug=SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [("horilla_tour", "0089_seed_hr_document_library_tour")]
    operations = [migrations.RunPython(seed, unseed)]
