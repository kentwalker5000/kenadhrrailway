"""Views for the HR-owned document library.

Employee document requests remain in ``employee.cbv.document_request``.  This
module deliberately handles only organisation/HR files that live in folders.
"""

from django.contrib import messages
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from horilla.decorators import login_required, permission_required

from horilla_documents.forms import HRDocumentFolderForm, HRLibraryDocumentForm
from horilla_documents.models import HRDocumentFolder, HRLibraryDocument


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _modal_success():
    """Close a popup and refresh the document library after a write."""
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("hr-document-library")
    return response


@login_required
@permission_required("horilla_documents.view_hrdocumentfolder")
def library(request):
    """Show folders and their HR-managed documents for the active company."""
    folders = HRDocumentFolder.objects.prefetch_related("documents").all()
    query = request.GET.get("search", "").strip()
    if query:
        # A person looking for "policy" expects both a folder named Policy
        # and a file called Leave policy to be found.
        folders = folders.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(documents__title__icontains=query)
            | Q(documents__description__icontains=query)
        ).distinct()
    context = {
        "folders": folders,
        "query": query,
        "nav_title": _("HR Document Library"),
        "search_url": reverse("hr-document-library"),
        "search_swap_target": "#hrDocumentLibraryContent",
        "search_input_attrs": format_html('value="{}"', query),
        "create_attrs": format_html(
            'id="hrDocumentCreateFolderButton" role="button" tabindex="0" data-toggle="oh-modal-toggle" '
            'data-target="#objectCreateModal" hx-get="{}" '
            'hx-target="#objectCreateModalTarget"',
            reverse("hr-document-folder-create"),
        ) if request.user.has_perm("horilla_documents.add_hrdocumentfolder") else "",
    }
    # Sidebar navigation needs the full shell for its HTMX swap; search only
    # swaps the library content.
    if _is_htmx(request) and request.headers.get("HX-Sidebar-Nav") != "true":
        return render(request, "hr_documents/library_content.html", context)
    return render(request, "hr_documents/library.html", context)


@login_required
@permission_required("horilla_documents.add_hrdocumentfolder")
def folder_create(request):
    form = HRDocumentFolderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("HR document folder created."))
        if _is_htmx(request):
            return _modal_success()
        return redirect("hr-document-library")
    return render(
        request,
        "hr_documents/library_form_modal.html" if _is_htmx(request) else "hr_documents/folder_form.html",
        {"form": form, "title": _("Create HR document folder"), "modal_target": "objectCreateModalTarget"},
    )


@login_required
@permission_required("horilla_documents.change_hrdocumentfolder")
def folder_edit(request, folder_id):
    folder = get_object_or_404(HRDocumentFolder.objects.all(), pk=folder_id)
    form = HRDocumentFolderForm(request.POST or None, instance=folder)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("HR document folder updated."))
        if _is_htmx(request):
            return _modal_success()
        return redirect("hr-document-library")
    return render(
        request,
        "hr_documents/library_form_modal.html" if _is_htmx(request) else "hr_documents/folder_form.html",
        {"form": form, "folder": folder, "title": _("Edit HR document folder"), "modal_target": "objectUpdateModalTarget"},
    )


@login_required
@permission_required("horilla_documents.delete_hrdocumentfolder")
@require_POST
def folder_delete(request, folder_id):
    folder = get_object_or_404(HRDocumentFolder.objects.all(), pk=folder_id)
    try:
        folder.delete()
    except ProtectedError:
        messages.error(request, _("Remove or move this folder's documents before deleting it."))
    else:
        messages.success(request, _("HR document folder deleted."))
    return _modal_success() if _is_htmx(request) else redirect("hr-document-library")


@login_required
@permission_required("horilla_documents.add_hrlibrarydocument")
def document_upload(request, folder_id):
    folder = get_object_or_404(HRDocumentFolder.objects.all(), pk=folder_id)
    document = HRLibraryDocument(folder=folder)
    form = HRLibraryDocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("HR document uploaded."))
        if _is_htmx(request):
            return _modal_success()
        return redirect("hr-document-library")
    return render(
        request,
        "hr_documents/library_form_modal.html" if _is_htmx(request) else "hr_documents/document_form.html",
        {
            "form": form,
            "folder": folder,
            "title": _("Upload to %(folder)s") % {"folder": folder.name},
            "cancel_url": reverse("hr-document-library"),
            "modal_target": "objectCreateModalTarget",
        },
    )


@login_required
@permission_required("horilla_documents.change_hrlibrarydocument")
def document_edit(request, document_id):
    document = get_object_or_404(HRLibraryDocument.objects.all(), pk=document_id)
    form = HRLibraryDocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("HR document updated."))
        if _is_htmx(request):
            return _modal_success()
        return redirect("hr-document-library")
    return render(
        request,
        "hr_documents/library_form_modal.html" if _is_htmx(request) else "hr_documents/document_form.html",
        {
            "form": form,
            "folder": document.folder,
            "title": _("Edit %(document)s") % {"document": document.title},
            "cancel_url": reverse("hr-document-library"),
            "modal_target": "objectUpdateModalTarget",
        },
    )


@login_required
@permission_required("horilla_documents.view_hrlibrarydocument")
def document_download(request, document_id):
    document = get_object_or_404(HRLibraryDocument.objects.all(), pk=document_id)
    if not document.document:
        raise Http404
    # Do not expose storage URLs in the template: every download passes the
    # authenticated, company-scoped permission check above.
    return FileResponse(
        document.document.open("rb"),
        as_attachment=True,
        filename=document.document.name.rsplit("/", 1)[-1],
    )


@login_required
@permission_required("horilla_documents.delete_hrlibrarydocument")
@require_POST
def document_delete(request, document_id):
    document = get_object_or_404(HRLibraryDocument.objects.all(), pk=document_id)
    document.delete()
    messages.success(request, _("HR document deleted."))
    return _modal_success() if _is_htmx(request) else redirect("hr-document-library")
