"""Secure server-rendered council member and document-library views."""

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from horilla.decorators import login_required, permission_required

from council.forms import CouncilDocumentForm, CouncilLibraryFolderForm, CouncilMemberForm
from council.models import CouncilDocument, CouncilLibraryFolder, CouncilMember


def _document_or_404(document_id):
    return get_object_or_404(CouncilDocument.objects.all(), pk=document_id)


@login_required
@permission_required("council.view_councilmember")
def member_list(request):
    members = CouncilMember.objects.all()
    term = request.GET.get("q", "").strip()
    if term:
        members = members.filter(full_name__icontains=term)
    return render(request, "council/member_list.html", {"members": members, "query": term})


@login_required
@permission_required("council.add_councilmember")
def member_create(request):
    form = CouncilMemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member = form.save()
        messages.success(request, _("Council member created."))
        return redirect("council-member-detail", member_id=member.pk)
    return render(request, "council/member_form.html", {"form": form, "title": _("Add council member")})


@login_required
@permission_required("council.view_councilmember")
def member_detail(request, member_id):
    member = get_object_or_404(CouncilMember.objects.all(), pk=member_id)
    documents = [document for document in member.documents.all() if document.user_can_view(request.user)]
    return render(request, "council/member_detail.html", {"member": member, "documents": documents})


@login_required
@permission_required("council.change_councilmember")
def member_edit(request, member_id):
    member = get_object_or_404(CouncilMember.objects.all(), pk=member_id)
    form = CouncilMemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Council member updated."))
        return redirect("council-member-detail", member_id=member.pk)
    return render(request, "council/member_form.html", {"form": form, "title": _("Edit council member"), "member": member})


@login_required
@permission_required("council.delete_councilmember")
@require_POST
def member_delete(request, member_id):
    member = get_object_or_404(CouncilMember.objects.all(), pk=member_id)
    member.delete()
    messages.success(request, _("Council member deleted."))
    return redirect("council-member-list")


@login_required
@permission_required("council.change_councildocument")
def member_document_upload(request, member_id):
    member = get_object_or_404(CouncilMember.objects.all(), pk=member_id)
    document = CouncilDocument(member=member)
    form = CouncilDocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Private council document uploaded."))
        return redirect("council-member-detail", member_id=member.pk)
    return render(
        request,
        "council/document_form.html",
        {"form": form, "title": _("Upload private document"), "cancel_url": reverse("council-member-detail", args=[member.pk])},
    )


@login_required
def library(request):
    # A restricted folder can be shared directly with a user who has no broad
    # library permission, so access is evaluated folder-by-folder rather than
    # being gated only by Django's global view permission.
    folders = [folder for folder in CouncilLibraryFolder.objects.all() if folder.user_can_view(request.user)]
    return render(request, "council/library.html", {"folders": folders})


@login_required
@permission_required("council.change_councillibraryfolder")
def folder_create(request):
    form = CouncilLibraryFolderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        folder = form.save()
        messages.success(request, _("Document folder created."))
        return redirect("council-library")
    return render(request, "council/folder_form.html", {"form": form, "title": _("Create document folder")})


@login_required
@permission_required("council.change_councillibraryfolder")
def folder_edit(request, folder_id):
    folder = get_object_or_404(CouncilLibraryFolder.objects.all(), pk=folder_id)
    form = CouncilLibraryFolderForm(request.POST or None, instance=folder)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Document folder updated."))
        return redirect("council-library")
    return render(request, "council/folder_form.html", {"form": form, "title": _("Edit document folder"), "folder": folder})


@login_required
@permission_required("council.change_councildocument")
def folder_document_upload(request, folder_id):
    folder = get_object_or_404(CouncilLibraryFolder.objects.all(), pk=folder_id)
    document = CouncilDocument(folder=folder)
    form = CouncilDocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Library document uploaded."))
        return redirect("council-library")
    return render(
        request,
        "council/document_form.html",
        {"form": form, "title": _("Upload to %(folder)s") % {"folder": folder.name}, "cancel_url": reverse("council-library")},
    )


@login_required
def document_download(request, document_id):
    document = _document_or_404(document_id)
    if not document.user_can_view(request.user):
        raise Http404
    # Always stream through this permission check: storage object URLs must not
    # be embedded in pages because they can bypass member/folder access rules.
    return FileResponse(document.document.open("rb"), as_attachment=True, filename=document.document.name.rsplit("/", 1)[-1])


@login_required
@permission_required("council.delete_councildocument")
@require_POST
def document_delete(request, document_id):
    document = _document_or_404(document_id)
    redirect_name, kwargs = ("council-library", {}) if document.folder_id else ("council-member-detail", {"member_id": document.member_id})
    document.delete()
    messages.success(request, _("Document deleted."))
    return redirect(redirect_name, **kwargs)
