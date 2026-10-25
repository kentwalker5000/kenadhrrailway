from django.contrib import admin

from horilla_documents.models import (
    Document,
    DocumentRequest,
    HRDocumentFolder,
    HRLibraryDocument,
)

# Register your models here.
admin.site.register(Document)
admin.site.register(DocumentRequest)
admin.site.register(HRDocumentFolder)
admin.site.register(HRLibraryDocument)
