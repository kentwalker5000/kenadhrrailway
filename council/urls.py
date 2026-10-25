from django.urls import path

from council import views


urlpatterns = [
    path("", views.member_list, name="council-member-list"),
    path("members/new/", views.member_create, name="council-member-create"),
    path("members/<int:member_id>/", views.member_detail, name="council-member-detail"),
    path("members/<int:member_id>/edit/", views.member_edit, name="council-member-edit"),
    path("members/<int:member_id>/delete/", views.member_delete, name="council-member-delete"),
    path("members/<int:member_id>/documents/upload/", views.member_document_upload, name="council-member-document-upload"),
    path("library/", views.library, name="council-library"),
    path("library/folders/new/", views.folder_create, name="council-folder-create"),
    path("library/folders/<int:folder_id>/edit/", views.folder_edit, name="council-folder-edit"),
    path("library/folders/<int:folder_id>/documents/upload/", views.folder_document_upload, name="council-folder-document-upload"),
    path("documents/<int:document_id>/download/", views.document_download, name="council-document-download"),
    path("documents/<int:document_id>/delete/", views.document_delete, name="council-document-delete"),
]
