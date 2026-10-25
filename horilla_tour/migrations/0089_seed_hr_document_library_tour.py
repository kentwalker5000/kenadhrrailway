"""Seed the guided walkthrough for the HR-owned document library."""

from django.db import migrations


SLUG = "hr-document-library-tour"

STEPS = [
    {
        "sequence": 1,
        "title": "HR Document Library",
        "description": "Use this library for organisation and HR records such as policies, compliance files, templates, and internal contracts. Employee-uploaded documents stay separate in their own staff records.",
        "element_selector": "#hrDocumentLibraryIntro",
        "side": "bottom",
        "align": "start",
    },
    {
        "sequence": 2,
        "title": "Find a folder or file",
        "description": "Search by folder name, document title, or description to quickly find the internal record you need.",
        "element_selector": "#filterForm input[name='search']",
        "side": "bottom",
        "align": "start",
    },
    {
        "sequence": 3,
        "title": "Create a folder",
        "description": "Start by creating a folder. Use clear names such as Policies, Compliance, or Board Records so files stay organised.",
        "element_selector": "#hrDocumentCreateFolderButton",
        "side": "bottom",
        "align": "end",
    },
    {
        "sequence": 4,
        "title": "Upload and manage files",
        "description": "Within each folder, use the upload arrow to add a file. The pencil edits folder or file details, and the X removes an item after confirmation.",
        "element_selector": ".hr-document-folder-actions",
        "side": "bottom",
        "align": "end",
    },
    {
        "sequence": 5,
        "title": "Download stored documents",
        "description": "Use the download action next to a file to save a copy. Files remain permission-controlled and separate from employee document uploads.",
        "element_selector": "#hrDocumentLibraryContent",
        "side": "top",
        "align": "start",
    },
]


def seed(apps, schema_editor):
    Tour = apps.get_model("horilla_tour", "Tour")
    TourStep = apps.get_model("horilla_tour", "TourStep")
    tour, created = Tour.objects.get_or_create(
        slug=SLUG,
        defaults={
            "title": "HR Document Library",
            "description": "A guided tour of HR folders, internal file uploads, and document actions.",
            "page_match": "hr-document-library",
            "match_type": "url_name",
            "audience": "all",
            "trigger": "auto_once",
            "priority": 65,
            "icon": "folder-open-outline",
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
    dependencies = [("horilla_tour", "0088_rebrand_default_tours")]
    operations = [migrations.RunPython(seed, unseed)]
