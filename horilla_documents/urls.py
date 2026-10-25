from django.urls import path

from horilla_documents import views


urlpatterns = [
    path("library/", views.library, name="hr-document-library"),
    path("library/folders/new/", views.folder_create, name="hr-document-folder-create"),
    path("library/folders/<int:folder_id>/edit/", views.folder_edit, name="hr-document-folder-edit"),
    path("library/folders/<int:folder_id>/delete/", views.folder_delete, name="hr-document-folder-delete"),
    path("library/folders/<int:folder_id>/upload/", views.document_upload, name="hr-document-upload"),
    path("library/documents/<int:document_id>/edit/", views.document_edit, name="hr-document-edit"),
    path("library/documents/<int:document_id>/download/", views.document_download, name="hr-document-download"),
    path("library/documents/<int:document_id>/delete/", views.document_delete, name="hr-document-delete"),
]
